"""Central config for the KB pipeline. Edit here, not in pipeline code."""

# (regex, replacement) applied in order, case-insensitive. Standardises terminology + currency.
TERMINOLOGY = [
    (r"\b(?:WC loan|working capital facility|working capital finance|cash[- ]credit)\b", "working capital loan"),
    (r"\bterm finance\b", "term loan"),
    (r"\b(?:bill discounting|invoice discounting)\b", "invoice financing"),
    (r"\b(?:ROI|rate of interest)\b", "interest rate"),
    (r"\b(?:CIBIL score|credit bureau score|bureau score)\b", "credit score"),
    (r"\b(?:foreclose|foreclosure|pre-closure|preclosure)\b", "prepayment"),
    (r"(?:Rs\.?|INR)\s?(?=\d)", "₹"),
    (r"\b(?:lakhs|lacs|lac)\b", "lakh"),
    (r"\bcrores\b", "crore"),
]

# Common caller phrasing mapped to vocabulary used in the policy and FAQ sources.
# Keep expansions narrow: broad terms such as "loan" can pull unrelated questions into scope.
QUERY_EXPANSIONS = [
    (r"\b(?:shop|company|firm|enterprise)\b", "business"),
    (r"\b(?:operating|trading|been open|been running)\b", "minimum business vintage years"),
    (r"\b\d+(?:\.\d+)?\s+months?\s+(?:old|in business)\b", "minimum business vintage years"),
    (r"\b(?:paperwork|papers|docs)\b", "documents"),
    (r"\b(?:prepare|preparing|bring)\b", "required"),
]

# Lines matching these are boilerplate (nav/footer/marketing CTAs/legal banners).
BOILERPLATE_PATTERNS = [
    r"^©|^&copy;|all rights reserved",
    r"^apply now$", r"^click here", r"subscribe to our newsletter",
    r"cookie", r"^skip to content", r"^confidential\b",
]
# A short line repeated across >= this many different sources is also treated as boilerplate.
BOILERPLATE_MIN_SOURCES = 3

# Heading/title keyword -> category. Used when a file's front matter says `category: auto` or is absent.
CATEGORY_RULES = [
    (r"eligib|qualif|credit score|loan amount|applicant", "eligibility_policy"),
    (r"rate|fee|charge|interest|pricing|prepay", "pricing_fees"),
    (r"document|kyc", "documents"),
    (r"process|timeline|disburs|steps", "process"),
    (r"complian|calling|do-not-call", "compliance"),
    (r"product|working capital|term loan|invoice", "product"),
    (r"contact|support", "contact"),
    (r"why|about", "about"),
]

# Conflict resolution: higher wins.
SOURCE_PRIORITY = {"policy": 3, "playbook": 2, "faq": 2, "website": 1}

# PII
PII_PATTERNS = {
    "EMAIL": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "PHONE": r"(?:\+91[\s-]?)?\b[6-9]\d{4}[\s-]?\d{5}\b",
    "PAN": r"\b[A-Z]{5}\d{4}[A-Z]\b",
    "AADHAAR": r"\b\d{4}\s\d{4}\s\d{4}\b",
}
# Business contact details that are public and intentionally kept.
PII_ALLOWLIST = {"support@kestrelcapital.example", "1800-123-4567"}

# Facts that must agree across sources. Each regex runs on normalised text; captured groups form the value.
FACT_PATTERNS = {
    "min_annual_turnover": r"annual turnover[^.\n]{0,60}?₹\s?(\d+(?:\.\d+)?)\s?lakh",
    "min_business_vintage": r"business vintage[^.\n]{0,50}?(\d+(?:\.\d+)?)\s?years?",
    "processing_fee": r"processing fee[^.\n]{0,40}?(\d+(?:\.\d+)?)\s*%(?:\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*%)?",
    "min_credit_score": r"credit score[^.\n]{0,50}?(\d{3})",
}

MAX_CHUNK_WORDS = 260
DEDUP_JACCARD = 0.7
MIN_WORDS = 5
