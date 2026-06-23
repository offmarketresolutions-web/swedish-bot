"""In-code message catalog for the customer-facing bot's TEMPLATED strings
(greetings, intake questions, escalation/contact prompts, chips). The bot's
free-form replies localize via the {locale} prompt directive; these fixed
strings localize here. Staff dashboard strings use Django gettext (.po) instead.

Adding a language = add a dict here + Swedish chip/FAQ rows in the DB (plan §11).
"""
from __future__ import annotations

T = {
    "en": {
        "greeting": "Hi! I'm Nordland VVS's assistant. I can help with heat pumps, "
                    "water pumps/wells and water filtration. Let's figure out what's going on.",
        "q_category": "To start, what kind of equipment is it?",
        "q_problem": "Got it. In a few words, what's the problem?",
        "q_brand": "Which brand is it?",
        "q_model": "What's the model? A photo of the rating/nameplate is perfect if you have one.",
        "q_error_code": "Is the machine showing any error or fault code? If so, a photo of the "
                        "display is perfect — or type the code. (You can skip this.)",
        "model_photo_nudge": "No problem — if you can, snap a photo of the rating/nameplate and I'll "
                             "read the exact model off it. Or type 'skip' and we'll do our best.",
        "pre_escalate_diag": "Before I pass this to a Nordland VVS technician, please describe the "
                             "problem in a bit more detail — and if the machine is showing any error "
                             "or fault code, send a photo of the display (it really helps the "
                             "technician). If there's no code, just let me know.",
        "reask": "Sorry, I didn't quite catch that. ",
        "reask_phone": "That doesn't look like a phone number. Please include the area or "
                       "country code — e.g. 070-123 45 67, or +44 20 7946 0958.",
        "contact_name": "What's your name?",
        "contact_phone": "What's the best phone number to reach you?",
        "contact_email": "And your email? (type 'skip' if you'd rather not share it.)",
        "contact_postal_code": "Finally, what's your postal code or address so we can route a technician?",
        "escalate_leadin": "I'd like to get a Nordland VVS technician to help with this. Can I take "
                           "a few details so they can follow up — what's your name?",
        "approval": "I have everything I need. Shall I send this to Nordland VVS so a technician "
                    "can follow up?",
        "thanks": "Thanks{name_sfx}! I've passed your details to Nordland VVS — they'll be in "
                  "touch{phone_sfx} as soon as they can. Is there anything else I can help with?",
        "not_yet": "No problem. Whenever you're ready, you can reach Nordland VVS through the "
                   "contact form on their website. Take care!",
        "need_contact": "To have a technician follow up I just need a phone number to reach you — "
                        "what's the best number?",
        "no_contact_close": "No problem. Without a phone number or email I can't have a technician "
                            "call you back — but you can always reach Nordland VVS through the contact "
                            "form on their website. Take care!",
        "handoff": "Based on what you've described, this is best handled by a Nordland VVS "
                   "technician so we get it exactly right. Shall I send your details to them?",
        "terminal": "You're all set — Nordland VVS will follow up. Anything else?",
        "chip_yes_send": "Yes, send to Nordland",
        "chip_not_yet": "Not yet",
        "welcome_back": "Welcome back — good to hear from you again; I can see we've helped you before.",
        "phone_connector": "on",
    },
    "sv": {
        "greeting": "Hej! Jag är Nordland VVS assistent. Jag kan hjälpa till med värmepumpar, "
                    "vattenpumpar/brunnar och vattenfilter. Låt oss ta reda på vad som händer.",
        "q_category": "Till att börja med, vilken typ av utrustning gäller det?",
        "q_problem": "Okej. Beskriv kort vad problemet är.",
        "q_brand": "Vilket märke är det?",
        "q_model": "Vilken modell är det? Ett foto av typskylten är perfekt om du har ett.",
        "q_error_code": "Visar maskinen någon fel- eller larmkod? Ett foto av displayen är perfekt "
                        "— eller skriv koden. (Du kan hoppa över detta.)",
        "model_photo_nudge": "Inga problem — om du kan, ta en bild på typskylten så läser jag av exakt "
                             "modell. Eller skriv 'skip' så gör vi vårt bästa.",
        "pre_escalate_diag": "Innan jag skickar detta vidare till en tekniker från Nordland VVS — "
                             "beskriv gärna problemet lite mer i detalj, och om maskinen visar någon "
                             "fel- eller larmkod, skicka en bild på displayen (det hjälper teknikern "
                             "mycket). Finns ingen kod, säg bara till.",
        "reask": "Förlåt, jag uppfattade inte riktigt. ",
        "reask_phone": "Det ser inte ut som ett telefonnummer. Ange gärna riktnummer eller "
                       "landskod — t.ex. 070-123 45 67, eller +46 70 123 45 67.",
        "contact_name": "Vad heter du?",
        "contact_phone": "Vilket telefonnummer når vi dig bäst på?",
        "contact_email": "Och din e-post? (skriv 'skip' om du hellre avstår.)",
        "contact_postal_code": "Slutligen, vilket postnummer eller adress har du så vi kan "
                               "skicka en tekniker?",
        "escalate_leadin": "Jag vill gärna att en tekniker från Nordland VVS hjälper dig med "
                           "detta. Får jag ta några uppgifter så de kan höra av sig — vad heter du?",
        "approval": "Jag har allt jag behöver. Ska jag skicka detta till Nordland VVS så att en "
                    "tekniker kan höra av sig?",
        "thanks": "Tack{name_sfx}! Jag har skickat dina uppgifter till Nordland VVS — de hör av "
                  "sig{phone_sfx} så snart de kan. Något mer jag kan hjälpa till med?",
        "not_yet": "Inga problem. När du är redo kan du nå Nordland VVS via kontaktformuläret på "
                   "deras webbplats. Ha det bra!",
        "need_contact": "För att en tekniker ska kunna höra av sig behöver jag bara ett "
                        "telefonnummer — vilket når dig bäst?",
        "no_contact_close": "Inga problem. Utan telefonnummer eller e-post kan jag tyvärr inte be en "
                            "tekniker ringa upp — men du når alltid Nordland VVS via kontaktformuläret "
                            "på deras webbplats. Ha det bra!",
        "handoff": "Utifrån det du beskrivit är detta något en tekniker från Nordland VVS bör "
                   "hantera. Ska jag skicka dina uppgifter till dem?",
        "terminal": "Då är allt klart — Nordland VVS hör av sig. Något mer?",
        "chip_yes_send": "Ja, skicka till Nordland",
        "chip_not_yet": "Inte än",
        "welcome_back": "Välkommen tillbaka — kul att höra från dig igen; jag ser att vi har hjälpt dig tidigare.",
        "phone_connector": "på",
    },
}


def t(locale: str, key: str, **fmt) -> str:
    table = T.get(locale) or T["en"]
    s = table.get(key) or T["en"].get(key, "")
    return s.format(**fmt) if fmt else s
