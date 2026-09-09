"""
Builds the assistant's system prompt from whatever company the caller (or
browser visitor) configures, instead of a fixed set of named personas -
any business works, not just the two examples this project shipped with
originally. See app/api/voice.py's /greeting and /turn endpoints (the
browser flow) and app/api/twilio_voice.py (real calls, configured via
TWILIO_COMPANY_NAME / TWILIO_COMPANY_DETAILS env vars) for where this
plugs in.
"""

import hashlib

_BASE_RULES = """
You are a voice assistant answering an incoming phone call on a company
helpline. The caller is speaking to you out loud and your reply will be
read back to them with text-to-speech, so:
- Keep replies short: 1-3 sentences, plain conversational language, no
  markdown, no bullet points, no headings.
- Never invent account-record facts you have no way of knowing (balances,
  transaction history, stored personal data). If asked for something like
  that, say so plainly and offer to transfer the call to a human agent.
  This does NOT apply to things the caller has already told you earlier
  in this same call (e.g. their name) - freely recall and use those;
  refusing to repeat back what someone just told you is not "protecting
  their data," it's just unhelpful.
- Stay strictly within the company's domain described below. For
  anything unrelated, politely say it's outside what you can help with
  on this line.
- If the caller sounds upset or asks for a person, offer to transfer to a
  human agent rather than insisting you can handle it.
- Always reply in the same language the caller just spoke in, even though
  these instructions are written in English - e.g. a caller speaking Urdu
  gets an Urdu reply, one speaking English gets an English reply. Each
  user message carries an explicit note on which language to reply in;
  follow that.
"""

# Bounds prompt size/cost for a very long pasted company description -
# a helpline knowledge base doesn't need to be a full manual to be useful,
# and an unbounded prompt slows every single turn down, not just this one.
_MAX_DETAILS_CHARS = 4000


def build_system_prompt(company_name: str, company_details: str) -> str:
    name = company_name.strip() or "this company"
    details = company_details.strip()[:_MAX_DETAILS_CHARS]
    knowledge_section = (
        f"Facts you may rely on about {name}:\n{details}"
        if details
        else (
            f"No specific details about {name} were provided beyond its name - "
            "answer only in very general terms and offer a human handoff for "
            "anything specific, rather than guessing at facts you don't have."
        )
    )
    return f"You are the automated helpline assistant for {name}.\n{_BASE_RULES}\n{knowledge_section}"


def default_greeting(company_name: str) -> str:
    name = company_name.strip() or "our company"
    return f"Thank you for calling {name}. How can I help you today?"


def greeting_cache_key(company_name: str) -> str:
    """A persona used to be looked up by a fixed id; a user-typed company
    name isn't a safe cache key as-is (arbitrary length/characters), so
    it's hashed. Used by both app/api/voice.py (serving cached greeting
    audio) and app/main.py (pre-warming the example templates' greetings
    at startup) so the two agree on the same key for the same name."""
    return hashlib.sha256(company_name.strip().lower().encode("utf-8")).hexdigest()


# Optional quick-fill starting points for the frontend's setup form (see
# GET /api/voice/templates) - convenience only. Any company name/details a
# user types in works just as well; these aren't special-cased anywhere
# else in the backend.
EXAMPLE_TEMPLATES = [
    {
        "name": "Jazz (telecom)",
        "details": """Jazz is a mobile network operator offering prepaid and postpaid SIMs.
Common bundles: daily, weekly, and monthly call/SMS/internet bundles,
activated by dialing short codes (e.g. *117# opens the bundle menu).
Balance check: dial *111# for prepaid balance and remaining bundle data.
Lost/stolen SIM: the line can be blocked immediately on request and a
replacement SIM issued at any Jazz franchise with a valid CNIC.
Bill disputes, SIM replacement, and number porting all require identity
verification that this automated line cannot perform, so those requests
should be transferred to a human agent.
Helpline for human agents: 111-597-597 (in-app), or *333# for the
interactive menu.""",
    },
    {
        "name": "Alliance Bank (retail banking)",
        "details": """Alliance Bank offers savings/current accounts, debit and credit cards,
and personal/auto/home loans.
Lost or stolen card: can be blocked immediately on request; a
replacement card is delivered within 5-7 working days.
Branch hours: Monday-Friday 9am-5pm, Saturday 9am-1pm; closed Sundays
and public holidays.
Balance inquiries, transaction disputes, and loan applications require
identity verification (CNIC + account PIN) that this automated line
cannot perform, so those requests should be transferred to a human agent
or directed to the mobile banking app.
24/7 human helpline: 111-234-234.""",
    },
]
