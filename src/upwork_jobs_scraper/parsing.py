"""Turn Upwork pages (as returned by ScrapeUnblocker) into :mod:`models` records.

Every page this package reads carries its data in the Nuxt payload
(see :mod:`upwork_jobs_scraper.nuxt`):

* job search (``/nx/search/jobs/``) -> ``vuex.jobsSearch``
* skill job feeds (``/freelance-jobs/<skill>/``) -> the page's ``asyncData`` entry
* job pages (``/jobs/~02...``) -> ``vuex.jobDetails``
"""

from __future__ import annotations

import datetime as _dt
import re
from html import unescape
from typing import Any

from .models import Job, RelatedSkill, SearchPage, SkillPage
from .nuxt import NuxtDataError, extract
from .urls import BASE_URL, job_url, skill_slug, skill_url


class UpworkError(Exception):
    """Base class for errors raised by this package."""


class UpworkParseError(UpworkError):
    """The page did not contain the expected Upwork data (worth retrying)."""


class LoginRequiredError(UpworkError):
    """Upwork redirected to its login page.

    Some search filters (budget, hourly rate, proposals, payment verified, sorting
    by client spend or rating) are only open to signed-in users.
    """


class JobNotFoundError(UpworkError):
    """The job does not exist or is not publicly visible (closed, private or removed)."""


class SkillNotFoundError(UpworkError):
    """Upwork has no public job feed for this skill slug."""


JOB_TYPES = {1: "fixed", 2: "hourly"}
EXPERIENCE_LEVELS = {1: "Entry level", 2: "Intermediate", 3: "Expert"}
_TIER_WORDS = {"entry": 1, "intermediate": 2, "expert": 3}

LESS_THAN_30 = "Less than 30 hrs/week"
MORE_THAN_30 = "More than 30 hrs/week"
_WORKLOADS = {
    "parttime": LESS_THAN_30,
    "fulltime": MORE_THAN_30,
    "less than 30 hrs/week": LESS_THAN_30,
    "more than 30 hrs/week": MORE_THAN_30,
    "30+ hrs/week": MORE_THAN_30,
}

# Upwork reports some client countries as ISO 3166 alpha-3 codes ("USA", "CAN")
# and others by name; map the common codes so the field is consistent.
COUNTRY_CODES = {
    "ARE": "United Arab Emirates",
    "ARG": "Argentina",
    "AUS": "Australia",
    "AUT": "Austria",
    "BEL": "Belgium",
    "BGD": "Bangladesh",
    "BRA": "Brazil",
    "CAN": "Canada",
    "CHE": "Switzerland",
    "CHL": "Chile",
    "CHN": "China",
    "COL": "Colombia",
    "CZE": "Czech Republic",
    "DEU": "Germany",
    "DNK": "Denmark",
    "EGY": "Egypt",
    "ESP": "Spain",
    "EST": "Estonia",
    "FIN": "Finland",
    "FRA": "France",
    "GBR": "United Kingdom",
    "GRC": "Greece",
    "HKG": "Hong Kong",
    "HUN": "Hungary",
    "IDN": "Indonesia",
    "IND": "India",
    "IRL": "Ireland",
    "ISR": "Israel",
    "ITA": "Italy",
    "JPN": "Japan",
    "KOR": "South Korea",
    "MEX": "Mexico",
    "MYS": "Malaysia",
    "NGA": "Nigeria",
    "NLD": "Netherlands",
    "NOR": "Norway",
    "NZL": "New Zealand",
    "PAK": "Pakistan",
    "PHL": "Philippines",
    "POL": "Poland",
    "PRT": "Portugal",
    "ROU": "Romania",
    "SAU": "Saudi Arabia",
    "SGP": "Singapore",
    "SWE": "Sweden",
    "THA": "Thailand",
    "TUR": "Turkey",
    "UKR": "Ukraine",
    "USA": "United States",
    "VNM": "Vietnam",
    "ZAF": "South Africa",
}

_TAG_RE = re.compile(r"<[^>]+>")
_SPACES_RE = re.compile(r"[ \t\r\f\v]+")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?"
    r"\s*(Z|[+-]\d{2}:?\d{2})?$"
)
_OPEN_JOBS_RE = re.compile(r"([\d,]+)\s+open jobs?", re.I)
_LOGIN_MARKERS = ("log in to your upwork account", "upwork login")


# --------------------------------------------------------------------------- #
# Small value helpers
# --------------------------------------------------------------------------- #


def clean_text(value: Any) -> str | None:
    """Strip HTML tags (e.g. search-term highlights), unescape entities, tidy spaces."""
    if not isinstance(value, str):
        return None
    text = unescape(_TAG_RE.sub("", value))
    lines = [_SPACES_RE.sub(" ", line).strip() for line in text.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text or None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def _positive(value: Any) -> float | None:
    """A money amount, or ``None`` when Upwork sends 0 for "not set"."""
    number = _num(value)
    return number if number is not None and number > 0 else None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def _amount(value: Any) -> float | None:
    return _positive(value.get("amount")) if isinstance(value, dict) else None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def parse_iso(value: Any) -> _dt.datetime | None:
    """Parse the ISO 8601 timestamps Upwork uses (``Z``, ``+0000`` or no offset = UTC)."""
    if not isinstance(value, str):
        return None
    match = _ISO_RE.match(value.strip())
    if not match:
        return None
    year, month, day, hour, minute, second, offset = match.groups()
    tz = _dt.timezone.utc
    if offset and offset != "Z":
        sign = -1 if offset[0] == "-" else 1
        digits = offset[1:].replace(":", "")
        tz = _dt.timezone(sign * _dt.timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
    try:
        stamp = _dt.datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
            tzinfo=tz,
        )
    except ValueError:
        return None
    return stamp.astimezone(_dt.timezone.utc)


def iso_utc(value: Any) -> str | None:
    """Normalise a timestamp to ``YYYY-MM-DDTHH:MM:SSZ`` (UTC)."""
    stamp = parse_iso(value)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ") if stamp else None


def normalize_country(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    return COUNTRY_CODES.get(value.upper(), value)


def normalize_workload(value: Any) -> str | None:
    """Map Upwork's workload labels (and search-result codes) to one wording."""
    if not isinstance(value, str) or not value.strip():
        return None
    key = value.strip().rsplit(".", 1)[-1].lower()
    return _WORKLOADS.get(key, _WORKLOADS.get(value.strip().lower(), value.strip()))


def experience_from_tier(tier: Any) -> str | None:
    """``contractorTier`` (1-3) or a search ``tierText`` code -> experience level."""
    if isinstance(tier, int) and not isinstance(tier, bool):
        return EXPERIENCE_LEVELS.get(tier)
    if isinstance(tier, str):
        lowered = tier.lower()
        for word, level in _TIER_WORDS.items():
            if word in lowered:
                return EXPERIENCE_LEVELS[level]
    return None


def _skill_names(items: Any) -> list[str]:
    names: list[str] = []
    for item in _list(items):
        if isinstance(item, str):
            name = item
        else:
            item = _dict(item)
            name = (
                item.get("prettyName")
                or item.get("prefLabel")
                or item.get("name")
                or item.get("freeText")
            )
        name = clean_text(name)
        if name and name not in names:
            names.append(name)
    return names


def _grouped_skill_names(items: Any) -> list[str]:
    """Skill names from ``sands.ontologySkills``: groups ("... Deliverables") hold the
    actual skills in ``children``."""
    flat: list[Any] = []
    for item in _list(items):
        children = _dict(item).get("children")
        flat.extend(children if isinstance(children, list) else [item])
    return _skill_names(flat)


def page_title(html: str) -> str:
    match = _TITLE_RE.search(html or "")
    return clean_text(match.group(1)) or "" if match else ""


def is_login_page(html: str) -> bool:
    title = page_title(html).lower()
    return any(marker in title for marker in _LOGIN_MARKERS)


def _state(html: str, what: str) -> dict[str, Any]:
    try:
        state = extract(html)
    except NuxtDataError as exc:
        raise UpworkParseError(f"no Upwork data on the {what} ({exc})") from None
    if not isinstance(state, dict):
        raise UpworkParseError(f"unexpected Upwork data on the {what}")
    return state


# --------------------------------------------------------------------------- #
# Job records
# --------------------------------------------------------------------------- #


def job_from_search(raw: dict[str, Any], *, query: str | None = None) -> Job | None:
    """A :class:`Job` from one ``jobsSearch.jobs`` entry."""
    job_id = raw.get("ciphertext")
    title = clean_text(raw.get("title"))
    if not isinstance(job_id, str) or not job_id or not title:
        return None
    job_type = JOB_TYPES.get(raw.get("type"))  # type: ignore[arg-type]
    hourly = _dict(raw.get("hourlyBudget"))
    fixed = _amount(raw.get("amount")) if job_type == "fixed" else None
    hourly_min = _positive(hourly.get("min")) if job_type == "hourly" else None
    hourly_max = _positive(hourly.get("max")) if job_type == "hourly" else None
    return Job(
        job_id=job_id,
        title=title,
        url=job_url(job_id),
        uid=str(raw["uid"]) if raw.get("uid") else None,
        source="search",
        query=query,
        description=clean_text(raw.get("description")),
        job_type=job_type,
        fixed_budget=fixed,
        hourly_min=hourly_min,
        hourly_max=hourly_max,
        currency="USD" if (fixed or hourly_min or hourly_max) else None,
        experience_level=experience_from_tier(raw.get("tierText")),
        duration=clean_text(raw.get("durationLabel")),
        workload=normalize_workload(raw.get("engagement")),
        skills=_skill_names(raw.get("attrs")),
        posted_at=iso_utc(raw.get("publishedOn") or raw.get("createdOn")),
        renewed_at=iso_utc(raw.get("renewedOn")),
    )


def job_from_feed(raw: dict[str, Any], *, skill: str | None = None) -> Job | None:
    """A :class:`Job` from one entry of a skill's job feed."""
    job_id = raw.get("ciphertext")
    title = clean_text(raw.get("title"))
    if not isinstance(job_id, str) or not job_id or not title:
        return None
    job_type = JOB_TYPES.get(raw.get("type"))  # type: ignore[arg-type]
    amount = _dict(raw.get("amount"))
    fixed = _positive(amount.get("amount")) if job_type == "fixed" else None
    # Feeds only carry the top of an hourly range ("up to $X/hr").
    hourly_max = _amount(raw.get("maxAmount")) if job_type == "hourly" else None
    currency = amount.get("currencyCode") if isinstance(amount.get("currencyCode"), str) else None
    return Job(
        job_id=job_id,
        title=title,
        url=job_url(job_id),
        source="skill",
        query=skill,
        description=clean_text(raw.get("description")),
        job_type=job_type,
        fixed_budget=fixed,
        hourly_max=hourly_max,
        currency=(currency or "USD") if (fixed or hourly_max) else None,
        experience_level=experience_from_tier(raw.get("contractorTier")),
        duration=clean_text(raw.get("durationLabel")),
        workload=normalize_workload(raw.get("engagement")),
        skills=_skill_names(raw.get("ontologySkills")),
        posted_at=iso_utc(raw.get("publishedOn") or raw.get("createdOn")),
        renewed_at=iso_utc(raw.get("renewedOn")),
    )


def job_from_details(details: dict[str, Any]) -> Job | None:
    """A fully detailed :class:`Job` from a job page's ``jobDetails`` state."""
    raw = details.get("job")
    if not isinstance(raw, dict):
        return None
    job_id = raw.get("ciphertext")
    title = clean_text(raw.get("title"))
    if not isinstance(job_id, str) or not job_id or not title:
        return None
    job_type = JOB_TYPES.get(raw.get("type"))  # type: ignore[arg-type]
    budget = _dict(raw.get("budget"))
    hourly = _dict(raw.get("extendedBudgetInfo"))
    fixed = _positive(budget.get("amount")) if job_type == "fixed" else None
    hourly_min = _positive(hourly.get("hourlyBudgetMin")) if job_type == "hourly" else None
    hourly_max = _positive(hourly.get("hourlyBudgetMax")) if job_type == "hourly" else None
    currency = budget.get("currencyCode") if isinstance(budget.get("currencyCode"), str) else None
    duration = _dict(raw.get("engagementDuration"))
    activity = _dict(raw.get("clientActivity"))
    quals = _dict(raw.get("qualifications"))
    sands = _dict(details.get("sands"))
    buyer = _dict(details.get("buyer"))
    stats = _dict(buyer.get("stats"))
    location = _dict(buyer.get("location"))
    company = _dict(buyer.get("company"))
    reviews = _int(stats.get("feedbackCount"))
    member_since = parse_iso(company.get("contractDate"))
    skills = _grouped_skill_names(sands.get("ontologySkills")) + _skill_names(
        sands.get("additionalSkills")
    )
    positions = raw.get("numberOfPositionsToHire") or activity.get("numberOfPositionsToHire")
    countries = [clean_text(c) for c in _list(quals.get("countries"))]
    return Job(
        job_id=job_id,
        title=title,
        url=job_url(job_id),
        uid=str(raw["uid"]) if raw.get("uid") else None,
        source="job",
        description=clean_text(raw.get("description")),
        job_type=job_type,
        fixed_budget=fixed,
        hourly_min=hourly_min,
        hourly_max=hourly_max,
        currency=(currency or "USD") if (fixed or hourly_min or hourly_max) else None,
        experience_level=experience_from_tier(raw.get("contractorTier")),
        duration=clean_text(duration.get("label") or raw.get("durationLabel")),
        duration_weeks=_int(duration.get("weeks")),
        workload=normalize_workload(raw.get("workload")),
        skills=list(dict.fromkeys(skills)),
        category=clean_text(_dict(raw.get("category")).get("name")),
        category_group=clean_text(_dict(raw.get("categoryGroup")).get("name")),
        occupation=clean_text(_dict(sands.get("occupation")).get("prefLabel")),
        posted_at=iso_utc(raw.get("publishTime") or raw.get("postedOn") or raw.get("createdOn")),
        positions=_int(positions),
        contract_to_hire=_bool(raw.get("isContractToHire")),
        proposals=_int(activity.get("totalApplicants")),
        interviewing=_int(activity.get("totalInvitedToInterview")),
        invites_sent=_int(activity.get("invitationsSent")),
        unanswered_invites=_int(activity.get("unansweredInvites")),
        hired=_int(activity.get("totalHired")),
        client_last_active_at=iso_utc(activity.get("lastBuyerActivity")),
        preferred_countries=[c for c in countries if c],
        min_job_success_score=_int(quals.get("minJobSuccessScore")) or None,
        client_country=normalize_country(location.get("country")),
        client_city=clean_text(location.get("city")),
        client_timezone=clean_text(location.get("countryTimezone")),
        client_payment_verified=_bool(buyer.get("isPaymentMethodVerified")),
        # Upwork shows a 0 score for clients nobody has reviewed yet.
        client_rating=_num(stats.get("score")) if reviews else None,
        client_reviews=reviews,
        client_total_spent=_amount(stats.get("totalCharges")) or (0.0 if stats else None),
        client_hires=_int(stats.get("totalAssignments")),
        client_active_hires=_int(stats.get("activeAssignmentsCount")),
        client_member_since=member_since.date().isoformat() if member_since else None,
        client_industry=clean_text(_dict(company.get("profile")).get("industry")),
        client_enterprise=_bool(buyer.get("isEnterprise")),
        details_fetched=True,
    )


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #


def parse_search_page(html: str, *, url: str = "", query: str | None = None) -> SearchPage:
    """Parse an Upwork job search results page.

    Raises:
        LoginRequiredError: Upwork answered with its login page.
        UpworkParseError: the page carries no search results data.
    """
    if is_login_page(html):
        raise LoginRequiredError(
            "Upwork asks signed-out visitors to log in for this search. Filters such as "
            "budget, hourly rate, proposals, payment verified and sorting by client spend "
            "or rating need an Upwork account; drop them and use the client-side filters "
            "of this package instead."
        )
    state = _state(html, "search page")
    search = _dict(_dict(state.get("vuex")).get("jobsSearch"))
    raw_jobs = search.get("jobs")
    status = _dict(search.get("status"))
    if not isinstance(raw_jobs, list) or status.get("failed") is True:
        raise UpworkParseError("search page has no job results")
    cached = _dict(search.get("searchQueryCache"))
    if query is None:
        query = cached.get("q") if isinstance(cached.get("q"), str) else ""
    jobs = [job_from_search(_dict(raw), query=query) for raw in raw_jobs]
    paging = _dict(search.get("paging"))
    return SearchPage(
        url=url,
        query=query or "",
        page=_int(search.get("currentPage")) or 1,
        per_page=_int(search.get("jobsPerPage")) or _int(paging.get("count")) or 10,
        total=_int(paging.get("total")),
        jobs=[j for j in jobs if j is not None],
    )


def _feed_data(state: dict[str, Any]) -> dict[str, Any] | None:
    for value in _dict(state.get("data")).values():
        if isinstance(value, dict) and isinstance(value.get("jobs"), list):
            if "totalJobs" in value or "skillRoute" in value:
                return value
    return None


def _related_skill(raw: Any) -> RelatedSkill | None:
    raw = _dict(raw)
    path = raw.get("urlPath") or raw.get("url")
    if not isinstance(path, str) or "/freelance-jobs/" not in path:
        return None
    try:
        slug = skill_slug(path)
    except ValueError:
        return None
    name = clean_text(raw.get("title")) or slug
    name = re.sub(r"\s+jobs$", "", name, flags=re.I)
    count = _OPEN_JOBS_RE.search(raw.get("description") or "")
    return RelatedSkill(
        slug=slug,
        name=name,
        url=skill_url(slug),
        open_jobs=int(count.group(1).replace(",", "")) if count else None,
    )


def parse_skill_page(html: str, *, url: str = "", skill: str | None = None) -> SkillPage:
    """Parse a skill's public job feed (``/freelance-jobs/<skill>/``).

    Raises:
        UpworkParseError: the page carries no job feed data.
    """
    state = _state(html, "skill page")
    feed = _feed_data(state)
    if feed is None:
        raise UpworkParseError("skill page has no job feed")
    route = _dict(_dict(feed.get("skillRoute")).get("params"))
    slug = route.get("skill") if isinstance(route.get("skill"), str) else None
    slug = slug or (skill_slug(skill) if skill else None) or (skill_slug(url) if url else "")
    jobs = [job_from_feed(_dict(raw), skill=slug) for raw in feed["jobs"]]
    related = [_related_skill(raw) for raw in _list(feed.get("relatedJobs"))]
    return SkillPage(
        slug=slug,
        name=clean_text(feed.get("prettySkillName") or feed.get("modifier")),
        url=url or (skill_url(slug) if slug else BASE_URL),
        total_jobs=_int(feed.get("totalJobs")),
        jobs=[j for j in jobs if j is not None],
        related_skills=[r for r in related if r is not None],
    )


def parse_job_page(html: str, *, url: str = "") -> Job:
    """Parse a job page into a fully detailed :class:`Job`.

    Raises:
        LoginRequiredError: Upwork answered with its login page.
        JobNotFoundError: the page loaded but shows no job (closed, private or removed).
        UpworkParseError: the page carries no job data at all.
    """
    if is_login_page(html):
        raise LoginRequiredError(f"Upwork asks for a login to view this job: {url}")
    state = _state(html, "job page")
    details = _dict(state.get("vuex")).get("jobDetails")
    if not isinstance(details, dict):
        raise UpworkParseError("job page has no job details")
    job = job_from_details(details)
    if job is None:
        raise JobNotFoundError(
            f"job is not publicly available (it may be closed, private or removed): {url}"
        )
    return job
