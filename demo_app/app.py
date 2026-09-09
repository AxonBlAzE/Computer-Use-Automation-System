"""Small server-rendered target, accessed by automation exclusively through its UI."""

import asyncio
from html import escape

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

app = FastAPI(title="Synthetic Member Services")
MEMBERS = {"12345": "Alex Sample", "67890": "Morgan Example"}
REQUESTS = {"statement": "Statement copy", "address": "Address review"}


def page(body: str) -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Member Services Sandbox</title><style>
body{font:17px system-ui;margin:3rem auto;max-width:760px;color:#173042;background:#f5f7fa}
main{padding:2rem;background:white;border:1px solid #dce3ea;border-radius:12px}
label{display:block;margin:1rem 0 .3rem}input,select,textarea{font:inherit;padding:.5rem;
box-sizing:border-box;width:100%}button{font:inherit;padding:.6rem 1rem;margin-top:1rem;
background:#174e69;color:white;border:0;border-radius:4px}table{width:100%;margin:1rem 0}
th{text-align:left}td,th{padding:.5rem;border-bottom:1px solid #ddd}
[role=alert]{padding:1rem;background:#fff0e8}.muted{color:#586b78;font-size:.9rem}
</style></head><body><main><p class="muted">SANDBOX / SYNTHETIC DATA ONLY</p>"""
        + body
        + "</main></body></html>"
    )


@app.get("/", response_class=HTMLResponse)
async def home():
    return page("""<h1>Member services</h1><form action="/members" method="get">
<label for="member">Member ID</label><input id="member" name="member_id" required>
<label for="scenario">Demo scenario</label><select id="scenario" name="scenario">
<option value="normal">Normal</option><option value="slow">Slow load</option>
</select><button type="submit">Find member</button></form>""")


@app.get("/members", response_class=HTMLResponse)
async def member(member_id: str = "", scenario: str = "normal"):
    if scenario == "slow":
        await asyncio.sleep(0.5)
    if member_id not in MEMBERS:
        return page(
            '<h1>Search results</h1><p role="status" aria-label="Member not found">'
            'Member not found</p><a href="/">Search again</a>'
        )
    return page(f"""<h1>Member details</h1><table><tr><th>Member ID</th>
<td>{escape(member_id)}</td></tr><tr><th>Name</th><td>{MEMBERS[member_id]}</td></tr></table>
<form action="/request" method="get"><input type="hidden" name="member_id"
value="{escape(member_id)}"><button>New service request</button></form>""")


@app.get("/request", response_class=HTMLResponse)
async def request_form(member_id: str = ""):
    if member_id not in MEMBERS:
        return page('<p role="status" aria-label="Member not found">Member not found</p>')
    return page(f"""<h1>Service request</h1><form action="/review" method="get">
<input type="hidden" name="member_id" value="{escape(member_id)}">
<label for="kind">Request type</label><select name="request_type" id="kind">
<option value="statement">Statement copy</option><option value="address">Address review</option>
</select><label for="note">Request note</label><textarea id="note" name="request_note"></textarea>
<button>Review request</button></form>""")


@app.get("/review", response_class=HTMLResponse)
async def review(
    member_id: str = "", request_type: str = "", request_note: str = Query(default="")
):
    if member_id not in MEMBERS:
        return page('<p role="status" aria-label="Member not found">Member not found</p>')
    if request_type not in REQUESTS or len(request_note.strip()) < 5:
        return page(
            '<h1>Request validation</h1><p role="alert" aria-label="Validation error">'
            "Choose a request type and enter a note with at least five characters.</p>"
        )
    return page(f"""<h1>Review request</h1><table>
<tr><th>Member ID</th><td role="status"
aria-label="Reviewed member ID">{escape(member_id)}</td></tr>
<tr><th>Request type</th><td role="status"
aria-label="Reviewed request type">{request_type}</td></tr>
<tr><th>Status</th><td role="status" aria-label="Review status">ready</td></tr></table>
<p>{escape(request_note)}</p><form action="/commit" method="post">
<button>Submit request</button></form>
<p class="muted">Final submission is outside replay policy.</p>
""")


@app.post("/commit", response_class=HTMLResponse)
async def commit():
    return page("<h1>Demo submission received</h1><p>No real transaction was performed.</p>")
