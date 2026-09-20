"""Phase 3+: Jev (TypeSafe AI) client.

INTENTIONALLY UNIMPLEMENTED. See README.md, "Jev verification status".

Every attempt to reach TypeSafe AI's docs (or reputable mirrors describing
their integration) from this environment was blocked at the network layer:
docs.typesafe.ai, docs.aimlapi.com, langchain.com, pydantic.dev, and
developers.cloudflare.com all returned EGRESS_BLOCKED. The only source that
did return anything was a web-search summarizer, and its two results
described mutually inconsistent APIs for the same product (different base
URLs, different SDK package names, different access models).

Writing a client against either unverified description would mean guessing
request/response syntax and silently risking fabricated topics,
relationships, or anchor text downstream. That's the one thing explicitly
ruled out for this project.

To unblock, provide one of:
  (a) the raw text/PDF of Jev's actual API reference, or
  (b) a working curl/Python example you've already run against it,
and this module gets implemented against that verified source -- along with
an answer to the open architectural question in the README: can Jev fetch
a URL's content itself, or must page content be supplied to it as input?
"""


class JevNotVerifiedError(RuntimeError):
    pass


def analyze_pages(pages: list[dict], api_key: str, base_url: str) -> list[dict]:
    raise JevNotVerifiedError(
        "Jev's API has not been verified from this environment. "
        "See README.md 'Jev verification status' for what's needed to unblock this."
    )
