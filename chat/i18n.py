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
        "q_postal_code": "What's the postal code where the equipment is installed? I need it to "
                         "check whether the address is within our service area.",
        "q_problem": "Got it. In a few words, what's the problem?",
        "q_brand": "Which brand is it?",
        "q_model": "What's the model? A photo of the rating/nameplate is perfect if you have one.",
        "q_error_code": "Is the machine showing any error or fault code? If so, a photo of the "
                        "display is perfect — or type the code. (You can skip this.)",
        "model_photo_nudge": "No problem — if you can, snap a photo of the rating/nameplate and I'll "
                             "read the exact model off it. Or type 'skip' and we'll do our best.",
        "brand_reconfirm": "Got it — should I switch to {brand} instead? I'll pull up the right "
                           "manual for it. (Yes to switch, or no to keep the original.)",
        "model_disambig": "Do you mean {options}? Tap the exact model so I load the right "
                          "manual — or pick another option below.",
        "model_search_prompt": "No problem — type the model exactly as it's written on the "
                               "rating/nameplate, or send a photo of the plate.",
        "chip_other_model": "Another model",
        "chip_none_of_these": "None of these",
        "confirm_fix": "Did that fix it?",
        # These used to end "A Nordland technician is being alerted." Nothing was alerted:
        # a lead only exists after the customer gives contact details AND approves sending
        # it. Someone standing outside a gas-leaking house, told to evacuate, very often
        # never finishes that — and believed help was already on the way when it was not.
        # Say what is true, and point at the help that actually comes fastest.
        # Fire had no line at all: "its on fire" fell through to the close-out template.
        "fire_emergency": "If something is burning or smoking: get everyone out of the "
                          "building now and call 112 from outside. Do not try to put it out "
                          "yourself and do not go back in for anything. When you are safe, "
                          "give me a phone number and I'll send this to Nordland VVS marked "
                          "urgent.",
        "gas_emergency": "If you smell gas: leave the building now, do not touch any switch, "
                         "breaker or light — a spark can ignite it — and call the emergency "
                         "number 112 from outside. 112 is the fastest help there is. "
                         "When you are safe, give me a phone number and I'll send this to "
                         "Nordland VVS marked urgent.",
        "refrigerant_emergency": "That sounds like it could be a refrigerant leak. Keep people "
                                 "and pets away from the unit, open windows to ventilate, no "
                                 "open flames or smoking nearby, and don't touch or operate the "
                                 "unit. Give me a phone number and I'll send this to Nordland "
                                 "VVS marked urgent.",
        "confirm_resolved": "Great — glad that sorted it! If anything else comes up, just let "
                            "me know.",
        # Offered AFTER the fix has been given, never before it — the answer is not held
        # back pending contact details. The reason is the customer's, not ours: a
        # specialist reviews the case and gets in touch if there's a better answer.
        "save_details_offer": "Glad that sorted it! Can I take your phone number and email? One of "
                              "our specialists reviews these cases, and if we have a better "
                              "suggestion for your unit we'll get in touch.",
        "save_details_done": "Thanks{name_sfx} — Nordland VVS has your details. A specialist will "
                             "look over the case and contact you if there's more we can do. All "
                             "the best!",
        "save_details_declined": "No problem. If anything else comes up, just let me know.",
        "pre_escalate_diag": "Before I pass this to a Nordland VVS technician, please describe the "
                             "problem in a bit more detail — and if the machine is showing any error "
                             "or fault code, send a photo of the display (it really helps the "
                             "technician). If there's no code, just let me know.",
        # Used when an error/alarm code is ALREADY on file — spec §2.3 forbids re-asking
        # for a fact the customer has given ("It's H01 5295. That's what I said.").
        "pre_escalate_diag_have_code": "Before I pass this to a Nordland VVS technician, please "
                             "describe the problem in a bit more detail — anything about when it "
                             "happens helps the technician.",
        "reask": "Sorry, I didn't quite catch that. ",
        # A turn that crashed on our side. Never blames the customer, and never asks them
        # to repeat something they already typed — their message is still on screen.
        "turn_failed": "Something went wrong on our side just now — that wasn't you. "
                       "Please send that again, or call us and we'll pick it up from here.",
        "reask_phone": "That doesn't look like a phone number. Please include the area or "
                       "country code — e.g. 070-123 45 67, or +44 20 7946 0958.",
        "contact_name": "What's your name?",
        "contact_phone": "What's the best phone number to reach you?",
        "contact_email": "And your email? (type 'skip' if you'd rather not share it.)",
        "contact_postal_code": "What's your postal code so we can route a technician?",
        "contact_address": "Finally, what's the installation address the equipment is at? "
                           "(street and number — type 'skip' if you'd rather not.)",
        "approval_address": "I'll note the installation address as {address}.",
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
        # The conversation is closed but the customer is still typing. Every message used to
        # get the line above, forever — "okay yea what do i do" and "yes" included, which
        # reads as a wall rather than an answer.
        "reopen": "Of course — tell me what's going on and I'll help.",
        "chip_yes_send": "Yes, send to Nordland",
        "chip_not_yet": "Not yet",
        "chip_notsure": "Not sure",
        "chip_other": "Other / not listed",
        "chip_dontknow": "I don't know",
        "chip_yes": "Yes",
        "chip_no": "No",
        "welcome_back": "Welcome back — good to hear from you again; I can see we've helped you before.",
        "phone_connector": "on",
        # S5 service-area gate
        "installer_ask": "Just to check — has Nordland VVS, Bylunds VVS or Nordborr i Sundsvall "
                         "installed your equipment?",
        "installer_which": "Which of them installed it? (just type the name)",
        "outside_area_decline": "Thanks for reaching out. Unfortunately the address falls outside "
                                "Nordland VVS's service area{area_sfx}, so I can't book a technician "
                                "visit there.",
        "coverage_confirm": "You're near the edge of our area, so a technician will confirm coverage "
                            "before the visit.",
        # S6 widget fallback for an old cached widget that sends "open_form" as text
        "form_link": "You can open the booking form here: {url}",
        # Feature 1 -- off-domain graceful close
        "off_domain_close": "It sounds like this isn't about heat pumps, water pumps/wells or "
                            "water filtration, so I'm not able to help with it here. I can help "
                            "with troubleshooting, service and quotes for heat pumps, water "
                            "pumps/wells and water filtration systems — happy to start over if "
                            "that changes. Take care!",
    },
    "sv": {
        "greeting": "Hej! Jag är Nordland VVS assistent. Jag kan hjälpa till med värmepumpar, "
                    "vattenpumpar/brunnar och vattenfilter. Låt oss ta reda på vad som händer.",
        "q_category": "Till att börja med, vilken typ av utrustning gäller det?",
        "q_postal_code": "Vilket postnummer finns anläggningen på? Jag behöver det för att "
                         "kontrollera om adressen ligger inom vårt arbetsområde.",
        "q_problem": "Okej. Beskriv kort vad problemet är.",
        "q_brand": "Vilket märke är det?",
        "q_model": "Vilken modell är det? Ett foto av typskylten är perfekt om du har ett.",
        "q_error_code": "Visar maskinen någon fel- eller larmkod? Ett foto av displayen är perfekt "
                        "— eller skriv koden. (Du kan hoppa över detta.)",
        "model_photo_nudge": "Inga problem — om du kan, ta en bild på typskylten så läser jag av exakt "
                             "modell. Eller skriv 'skip' så gör vi vårt bästa.",
        "brand_reconfirm": "Okej — ska jag byta till {brand} istället? Då tar jag fram rätt manual. "
                           "(Ja för att byta, eller nej för att behålla den ursprungliga.)",
        "model_disambig": "Menar du {options}? Tryck på exakt modell så tar jag fram rätt "
                          "manual — eller välj ett annat alternativ nedan.",
        "model_search_prompt": "Inga problem — skriv modellen exakt som den står på typskylten, "
                               "eller skicka ett foto av skylten.",
        "chip_other_model": "Annan modell",
        "chip_none_of_these": "Ingen av dessa",
        "confirm_fix": "Löste det problemet?",
        "fire_emergency": "Om något brinner eller ryker: få ut alla ur byggnaden nu och ring "
                          "112 utifrån. Försök inte släcka själv, och gå inte in igen för att "
                          "hämta något. När du är i säkerhet: ge mig ett telefonnummer, så "
                          "skickar jag ärendet till Nordland VVS märkt brådskande.",
        "gas_emergency": "Om det luktar gas: lämna byggnaden nu, rör inga strömbrytare, säkringar "
                         "eller lampor — en gnista kan antända gasen — och ring nödnumret 112 "
                         "utifrån. 112 är den hjälp som kommer snabbast. "
                         "När du är i säkerhet: ge mig ett telefonnummer, så skickar jag ärendet "
                         "till Nordland VVS märkt brådskande.",
        "refrigerant_emergency": "Det låter som att det kan vara ett köldmedieläckage. Håll "
                                 "människor och husdjur borta från enheten, öppna fönster och "
                                 "vädra, ingen öppen eld eller rökning i närheten, och rör eller "
                                 "hantera inte enheten. Ge mig ett telefonnummer, så skickar jag "
                                 "ärendet till Nordland VVS märkt brådskande.",
        "confirm_resolved": "Vad bra — kul att det löste sig! Hör av dig om något mer dyker upp.",
        "save_details_offer": "Vad bra att det löste sig! Får jag ta ditt telefonnummer och din "
                              "e-post? En av våra specialister går igenom ärendet, och har vi ett "
                              "bättre förslag för din anläggning hör vi av oss.",
        "save_details_done": "Tack{name_sfx} — Nordland VVS har dina uppgifter. En specialist tittar "
                             "på ärendet och hör av sig om det finns mer vi kan göra. Ha det bra!",
        "save_details_declined": "Inga problem. Hör av dig om något mer dyker upp.",
        "pre_escalate_diag": "Innan jag skickar detta vidare till en tekniker från Nordland VVS — "
                             "beskriv gärna problemet lite mer i detalj, och om maskinen visar någon "
                             "fel- eller larmkod, skicka en bild på displayen (det hjälper teknikern "
                             "mycket). Finns ingen kod, säg bara till.",
        "pre_escalate_diag_have_code": "Innan jag skickar detta vidare till en tekniker från "
                             "Nordland VVS — beskriv gärna problemet lite mer i detalj, allt om när "
                             "det händer hjälper teknikern.",
        "reask": "Förlåt, jag uppfattade inte riktigt. ",
        "turn_failed": "Något gick fel hos oss just nu — det var inte du. "
                       "Skicka gärna igen, eller ring oss så tar vi det därifrån.",
        "reask_phone": "Det ser inte ut som ett telefonnummer. Ange gärna riktnummer eller "
                       "landskod — t.ex. 070-123 45 67, eller +46 70 123 45 67.",
        "contact_name": "Vad heter du?",
        "contact_phone": "Vilket telefonnummer når vi dig bäst på?",
        "contact_email": "Och din e-post? (skriv 'skip' om du hellre avstår.)",
        "contact_postal_code": "Vilket postnummer har du så vi kan skicka en tekniker?",
        "contact_address": "Vilken adress är anläggningen installerad på? (gata och nummer "
                           "— skriv 'skip' om du hellre avstår.)",
        "approval_address": "Jag noterar installationsadressen som {address}.",
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
        "reopen": "Självklart — berätta vad det gäller så hjälper jag dig.",
        "chip_yes_send": "Ja, skicka till Nordland",
        "chip_not_yet": "Inte än",
        "chip_notsure": "Vet inte",
        "chip_other": "Annat / inte listat",
        "chip_dontknow": "Jag vet inte",
        "chip_yes": "Ja",
        "chip_no": "Nej",
        "welcome_back": "Välkommen tillbaka — kul att höra från dig igen; jag ser att vi har hjälpt dig tidigare.",
        "phone_connector": "på",
        # S5 service-area gate
        "installer_ask": "Bara för att kolla — har Nordland VVS, Bylunds VVS eller Nordborr i "
                         "Sundsvall installerat er anläggning?",
        "installer_which": "Vilket av dem installerade den? (skriv bara namnet)",
        "outside_area_decline": "Tack för att du hörde av dig. Tyvärr ligger adressen utanför "
                                "Nordland VVS arbetsområde{area_sfx}, så jag kan inte boka ett "
                                "teknikerbesök där.",
        "coverage_confirm": "Ni ligger nära kanten av vårt område, så en tekniker bekräftar "
                            "täckningen innan besöket.",
        # S6 widget fallback for an old cached widget that sends "open_form" as text
        "form_link": "Du kan öppna bokningsformuläret här: {url}",
        # Feature 1 -- off-domain graceful close
        "off_domain_close": "Det här verkar inte handla om värmepumpar, vattenpumpar/brunnar "
                            "eller vattenfilter, så jag kan tyvärr inte hjälpa till med det här. "
                            "Jag kan hjälpa till med felsökning, service och offerter för "
                            "värmepumpar, vattenpumpar/brunnar och vattenfiltersystem — säg "
                            "gärna till om det ändrar sig. Ha det bra!",
    },
}


def t(locale: str, key: str, **fmt) -> str:
    table = T.get(locale) or T["en"]
    s = table.get(key) or T["en"].get(key, "")
    return s.format(**fmt) if fmt else s
