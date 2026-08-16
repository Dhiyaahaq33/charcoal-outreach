"""Template WA & Email, disusun dari contoh nyata yang dipakai user (offer ke T And M Kestekides
Trading, Cyprus). Personalisasi lewat variabel per baris sheet: Company, ContactPerson,
ProductInterest, Country. Product list dipangkas biar relevan sama ProductInterest klien, bukan
selalu full list - kalau ProductInterest gak match salah satu produk di bawah, tampilkan full list
sebagai fallback (aman daripada kosong).

SENDER_* diisi tetap sesuai signature: Muhammad Yahya, COO, PT Cahaya Woodchar International.
"""

SENDER_NAME = "Muhammad Yahya"
SENDER_TITLE = "Chief Operating Officer"
SENDER_COMPANY = "PT Cahaya Woodchar International"
SENDER_EMAIL = "johanneshaq@gmail.com"
SENDER_PHONES = ["+62 895-0481-5988", "+62 812-2564-6585"]
SENDER_CATALOGUE_URL = "https://cahayawoodchar.com"

_ALL_PRODUCTS = [
    "Hardwood Charcoal (Halaban, Acacia, Rosewood)",
    "Mix Hardwood Charcoal",
    "BBQ Hardwood Charcoal Briquettes",
    "Coconut Shell Charcoal",
    "Binchotan-Style White Charcoal",
    "Sawdust Charcoal",
]


def _relevant_products(product_interest):
    pi = (product_interest or "").lower()
    matched = [p for p in _ALL_PRODUCTS if any(kw in pi for kw in p.lower().split(" (")[0].split())]
    return matched or _ALL_PRODUCTS


def _first_name(contact_person):
    name = (contact_person or "").strip()
    return name.split()[0] if name else "there"


def render_email(client_row, round_number):
    company = client_row.get("Company", "").strip() or "your company"
    contact = _first_name(client_row.get("Contact Person"))
    product_interest = client_row.get("Product Interest", "").strip()
    country = client_row.get("Country", "").strip()

    products = _relevant_products(product_interest)
    product_lines = "\n".join(f"✅ {p}" for p in products)

    opening = {
        1: f"We came across {company} and understand that you are currently sourcing "
           f"{product_interest or 'charcoal'} in {country}. We believe our products could be a "
           f"good fit for your requirements.",
        2: f"Following up on our previous message - we'd still love the opportunity to supply "
           f"{company} with high-quality charcoal from Indonesia.",
        3: f"This is a final follow-up regarding a potential charcoal supply partnership with "
           f"{company}. We understand timing may not be right, but wanted to leave the door open.",
    }[round_number]

    subject = {
        1: f"Charcoal Supply Partnership – PT Cahaya Woodchar International x {company}",
        2: f"Following Up – Charcoal Supply for {company}",
        3: f"Last Follow-Up – Charcoal Supply for {company}",
    }[round_number]

    body = f"""Dear {contact},

My name is {SENDER_NAME}, {SENDER_TITLE} at {SENDER_COMPANY}, a charcoal exporter based in \
Lampung, Indonesia.

{opening}

We can supply:
{product_lines}

Our wood charcoal can be supplied according to your requirements, including wood type, lump \
size, fixed carbon, ash content, moisture, packaging, and order volume.

Why partner with us:

* Competitive FOB/CIF pricing
* Consistent export-grade quality
* Reliable supply from Indonesia
* Customizable packaging
* Flexible export and shipping arrangements

Could you please share your preferred charcoal specifications and estimated order volume? I can \
send you our product specifications, photos, current pricing, and sample arrangement details.

Product catalogue: {SENDER_CATALOGUE_URL}

Best regards,
{SENDER_NAME}
{SENDER_TITLE}
{SENDER_COMPANY}
\U0001F4E7 {SENDER_EMAIL}
{chr(10).join(f"\U0001F4F1 {p}" for p in SENDER_PHONES)}
"""
    return subject, body


def render_whatsapp(client_row, round_number):
    company = client_row.get("Company", "").strip() or "your company"
    contact = _first_name(client_row.get("Contact Person"))
    product_interest = client_row.get("Product Interest", "").strip()
    country = client_row.get("Country", "").strip()

    products = _relevant_products(product_interest)
    product_lines = "\n".join(f"✅ {p}" for p in products)

    intro = {
        1: (f"Hi {contact}, this is {SENDER_NAME} from *{SENDER_COMPANY}*, a charcoal exporter "
            f"based in Lampung, Indonesia. We saw {company} sources "
            f"{product_interest or 'charcoal'} in {country} and wanted to introduce ourselves."),
        2: (f"Hi {contact}, following up on my earlier message - still keen to explore a charcoal "
            f"supply partnership with {company} if the timing works for you."),
        3: (f"Hi {contact}, last check-in from {SENDER_COMPANY} regarding charcoal supply for "
            f"{company}. Happy to reconnect anytime in the future if it's not a fit right now."),
    }[round_number]

    return (
        f"{intro}\n\n"
        f"We can supply:\n{product_lines}\n\n"
        f"Could you share your preferred specs & estimated order volume? Happy to send our "
        f"catalogue, pricing, and sample details.\n"
        f"Catalogue: {SENDER_CATALOGUE_URL}\n\n"
        f"Best,\n{SENDER_NAME} | {SENDER_TITLE}, {SENDER_COMPANY}"
    )
