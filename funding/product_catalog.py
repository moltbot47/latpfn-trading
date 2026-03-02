"""Pre-loaded business funding product catalog.

Comprehensive catalog of 80+ business funding products including major banks,
credit unions, neobanks, fintech lenders, and SBA programs. Bureau pull data
sourced from public lender disclosures and community-reported data.

Reference URLs point to each lender's official product page for verification.
"""

from .database import FundingDB
from .models import FundingProduct, PartnerProgram

# Helper to reduce boilerplate
_P = FundingProduct

PRODUCTS = [

    # ═════════════════════════════════════════════════════════════════
    # MAJOR BANK BUSINESS CREDIT CARDS
    # ═════════════════════════════════════════════════════════════════

    # ── Chase (5/24 rule — apply FIRST) ──────────────────────────────

    _P(lender="Chase", product_name="Ink Business Preferred",
       product_type="credit_card", min_score=700,
       typical_limit_low=5000, typical_limit_high=50000,
       bureau_pulled="Experian", inquiry_sensitive=True,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=95, recommended_order=1, category="premium",
       reference_url="https://creditcards.chase.com/business-credit-cards/ink/business-preferred",
       limit_source_url="https://www.doctorofcredit.com/chase-ink-business-preferred-credit-card-100000-point-offer/",
       notes="5/24 rule. 3x travel/shipping/advertising/social. 100k SUB potential."),

    _P(lender="Chase", product_name="Ink Business Unlimited",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=35000,
       bureau_pulled="Experian", inquiry_sensitive=True,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=2, category="mid_tier",
       reference_url="https://creditcards.chase.com/business-credit-cards/ink/business-unlimited",
       limit_source_url="https://www.doctorofcredit.com/chase-ink-business-unlimited/",
       notes="5/24 rule. 1.5% unlimited cashback. 0% intro APR 12 months."),

    _P(lender="Chase", product_name="Ink Business Cash",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Experian", inquiry_sensitive=True,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=3, category="mid_tier",
       reference_url="https://creditcards.chase.com/business-credit-cards/ink/cash",
       limit_source_url="https://www.doctorofcredit.com/chase-ink-business-cash/",
       notes="5/24 rule. 5% office supplies/internet/phone, 2% gas/dining."),

    _P(lender="Chase", product_name="Ink Business Premier",
       product_type="credit_card", min_score=720,
       typical_limit_low=5000, typical_limit_high=50000,
       bureau_pulled="Experian", inquiry_sensitive=True,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=195, recommended_order=4, category="ultra_premium",
       reference_url="https://creditcards.chase.com/business-credit-cards/ink/business-premier",
       limit_source_url="https://www.doctorofcredit.com/chase-ink-business-premier/",
       notes="5/24 rule. 2.5% on $5k+ purchases, 2% all other. $1k SUB."),

    # ── American Express ─────────────────────────────────────────────

    _P(lender="Amex", product_name="Business Gold Card",
       product_type="credit_card", min_score=680,
       typical_limit_low=10000, typical_limit_high=50000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=375, recommended_order=10, category="premium",
       reference_url="https://www.americanexpress.com/us/credit-cards/business/business-credit-cards/american-express-business-gold-card-amex/",
       limit_source_url="https://www.doctorofcredit.com/american-express-business-gold-card/",
       notes="4x on top 2 categories (up to $150k/yr). Charge card — no preset limit."),

    _P(lender="Amex", product_name="Business Platinum Card",
       product_type="credit_card", min_score=700,
       typical_limit_low=10000, typical_limit_high=100000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=695, recommended_order=11, category="ultra_premium",
       reference_url="https://www.americanexpress.com/us/credit-cards/business/business-credit-cards/american-express-business-platinum-credit-card-amex/",
       limit_source_url="https://www.doctorofcredit.com/american-express-business-platinum-card/",
       notes="5x flights/prepaid hotels. No preset limit. Centurion lounge. High SUB."),

    _P(lender="Amex", product_name="Blue Business Plus",
       product_type="credit_card", min_score=660,
       typical_limit_low=5000, typical_limit_high=25000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=12, category="mid_tier",
       reference_url="https://www.americanexpress.com/us/credit-cards/business/business-credit-cards/blue-business-plus-credit-card-amex/",
       limit_source_url="https://www.doctorofcredit.com/american-express-blue-business-plus/",
       notes="2x MR on all purchases (up to $50k/yr). 0% intro 12 months. No AF."),

    _P(lender="Amex", product_name="Blue Business Cash",
       product_type="credit_card", min_score=660,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=13, category="mid_tier",
       reference_url="https://www.americanexpress.com/us/credit-cards/business/business-credit-cards/blue-business-cash-card-amex/",
       limit_source_url="https://www.doctorofcredit.com/american-express-blue-business-cash/",
       notes="2% cashback on first $50k/yr. 0% intro 12 months. No AF."),

    _P(lender="Amex", product_name="Amazon Business Prime",
       product_type="credit_card", min_score=670,
       typical_limit_low=5000, typical_limit_high=30000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=14, category="mid_tier",
       reference_url="https://www.americanexpress.com/us/credit-cards/business/business-credit-cards/amazon-business-prime-card/",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/amazon-business-prime-amex",
       notes="5% back at Amazon/Whole Foods with Prime. 2% restaurants/gas/wireless. No AF."),

    _P(lender="Amex", product_name="Hilton Honors Business",
       product_type="credit_card", min_score=670,
       typical_limit_low=5000, typical_limit_high=30000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=195, recommended_order=15, category="premium",
       reference_url="https://www.americanexpress.com/us/credit-cards/business/business-credit-cards/hilton-honors-business-credit-card-amex/",
       limit_source_url="https://www.doctorofcredit.com/amex-hilton-honors-business/",
       notes="12x Hilton, 6x gas/dining/wireless. Free night annually. Weekend night reward."),

    _P(lender="Amex", product_name="Delta SkyMiles Reserve Business",
       product_type="credit_card", min_score=700,
       typical_limit_low=5000, typical_limit_high=40000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=650, recommended_order=16, category="ultra_premium",
       reference_url="https://www.americanexpress.com/us/credit-cards/business/business-credit-cards/delta-reserve-business-credit-card-amex/",
       limit_source_url="https://www.doctorofcredit.com/amex-delta-reserve-business/",
       notes="3x on Delta, 1x all else. Centurion lounge. Companion certificate."),

    # ── Capital One ──────────────────────────────────────────────────

    _P(lender="Capital One", product_name="Spark Cash Plus",
       product_type="credit_card", min_score=700,
       typical_limit_low=10000, typical_limit_high=50000,
       bureau_pulled="TransUnion,Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=150, recommended_order=20, category="premium",
       reference_url="https://www.capitalone.com/small-business/credit-cards/spark-cash-plus/",
       limit_source_url="https://www.doctorofcredit.com/capital-one-spark-cash-plus/",
       notes="Unlimited 2% cashback. Charge card (no preset limit). May pull multiple bureaus."),

    _P(lender="Capital One", product_name="Spark 1.5% Cash Select",
       product_type="credit_card", min_score=660,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="TransUnion,Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=21, category="mid_tier",
       reference_url="https://www.capitalone.com/small-business/credit-cards/spark-cash-select/",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/capital-one-spark-cash-select",
       notes="1.5% unlimited cashback. 0% intro 12 months. No AF."),

    _P(lender="Capital One", product_name="Spark 2% Cash Plus Select",
       product_type="credit_card", min_score=680,
       typical_limit_low=5000, typical_limit_high=30000,
       bureau_pulled="TransUnion,Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=22, category="mid_tier",
       reference_url="https://www.capitalone.com/small-business/credit-cards/spark-cash-plus-select/",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/capital-one-spark-cash-plus-select",
       notes="2% unlimited cashback. 0% intro 12 months. No AF. Newer product."),

    # ── Bank of America ──────────────────────────────────────────────

    _P(lender="Bank of America", product_name="Business Advantage Customized Cash",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=9,
       annual_fee=0, recommended_order=23, category="mid_tier",
       reference_url="https://www.bankofamerica.com/smallbusiness/credit-cards/business-advantage-customized-cash-rewards/",
       limit_source_url="https://www.doctorofcredit.com/bank-of-america-business-advantage-customized-cash/",
       notes="3% in chosen category, 2% dining. Preferred Rewards bonus up to 75%."),

    _P(lender="Bank of America", product_name="Business Advantage Unlimited Cash",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=9,
       annual_fee=0, recommended_order=24, category="mid_tier",
       reference_url="https://www.bankofamerica.com/smallbusiness/credit-cards/business-advantage-unlimited-cash-back/",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/bank-of-america-business-advantage-unlimited-cash-rewards",
       notes="1.5% unlimited cashback. 0% intro 9 months. Preferred Rewards up to 75% bonus."),

    _P(lender="Bank of America", product_name="Business Advantage Travel Rewards",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=9,
       annual_fee=0, recommended_order=25, category="mid_tier",
       reference_url="https://www.bankofamerica.com/smallbusiness/credit-cards/business-advantage-travel-rewards/",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/bank-of-america-business-advantage-travel-rewards",
       notes="1.5x points on all purchases. No AF. No foreign transaction fees."),

    # ── US Bank ──────────────────────────────────────────────────────

    _P(lender="US Bank", product_name="Business Triple Cash Rewards",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=15,
       annual_fee=0, recommended_order=26, category="mid_tier",
       reference_url="https://www.usbank.com/credit-cards/business-triple-cash-rewards-visa-business-card.html",
       limit_source_url="https://www.doctorofcredit.com/us-bank-business-triple-cash-rewards/",
       notes="3% gas/EV/office/cell/restaurant. 0% intro APR 15 months (LONGEST). No AF."),

    _P(lender="US Bank", product_name="Business Leverage Visa",
       product_type="credit_card", min_score=680,
       typical_limit_low=5000, typical_limit_high=30000,
       bureau_pulled="TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=27, category="mid_tier",
       reference_url="https://www.usbank.com/credit-cards/business-leverage-visa-signature-business-card.html",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/us-bank-business-leverage-visa-signature",
       notes="2% on top 2 categories (gas, office, cell, restaurant, airline, hotel). No AF."),

    # ── Wells Fargo ──────────────────────────────────────────────────

    _P(lender="Wells Fargo", product_name="Signify Business Cash",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=28, category="mid_tier",
       reference_url="https://www.wellsfargo.com/biz/business-credit/credit-cards/signify-business-cash-card/",
       limit_source_url="https://www.doctorofcredit.com/wells-fargo-signify-business-cash/",
       notes="2% cashback on all purchases. 0% intro 12 months. No AF."),

    _P(lender="Wells Fargo", product_name="Business Elite Signature",
       product_type="credit_card", min_score=720,
       typical_limit_low=25000, typical_limit_high=100000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=125, recommended_order=29, category="premium",
       reference_url="https://www.wellsfargo.com/biz/business-credit/credit-cards/elite-card/",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/wells-fargo-business-elite-signature",
       notes="High-limit card for established businesses. Customizable rewards. $25k min CL."),

    # ── Citi ─────────────────────────────────────────────────────────

    _P(lender="Citi", product_name="Costco Anywhere Visa Business",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=30, category="mid_tier",
       reference_url="https://www.citi.com/credit-cards/citi-costco-anywhere-visa-business-credit-card",
       limit_source_url="https://www.doctorofcredit.com/citi-costco-anywhere-visa-business/",
       notes="4% gas (up to $7k), 3% restaurants/travel, 2% Costco, 1% all else. Costco membership required."),

    # ═════════════════════════════════════════════════════════════════
    # CREDIT UNIONS — THE HIDDEN GEMS
    # ═════════════════════════════════════════════════════════════════

    # ── Navy Federal Credit Union ────────────────────────────────────

    _P(lender="Navy Federal", product_name="Business Visa Credit Card",
       product_type="credit_card", min_score=650,
       typical_limit_low=5000, typical_limit_high=50000,
       bureau_pulled="TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=35, category="mid_tier",
       reference_url="https://www.navyfederal.org/loans-cards/credit-cards/business.html",
       limit_source_url="https://www.doctorofcredit.com/navy-federal-credit-union-credit-card-reviews/",
       notes="Military/DOD members. Known for high limits. 0% intro 12 months. TransUnion only."),

    _P(lender="Navy Federal", product_name="Business Real Rewards",
       product_type="credit_card", min_score=660,
       typical_limit_low=5000, typical_limit_high=50000,
       bureau_pulled="TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=36, category="mid_tier",
       reference_url="https://www.navyfederal.org/loans-cards/credit-cards/business.html",
       limit_source_url="https://www.doctorofcredit.com/navy-federal-credit-union-credit-card-reviews/",
       notes="Military/DOD. 1.5x points on all purchases. Generous CLIs. TransUnion only pull."),

    # ── PenFed Credit Union ──────────────────────────────────────────

    _P(lender="PenFed", product_name="Pathfinder Business Visa",
       product_type="credit_card", min_score=680,
       typical_limit_low=5000, typical_limit_high=30000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=37, category="mid_tier",
       reference_url="https://www.penfed.org/credit-cards/pathfinder-rewards-business-visa",
       limit_source_url="https://www.doctorofcredit.com/penfed-pathfinder-rewards-visa/",
       notes="Anyone can join. 3x travel, 1.5x all else. Equifax pull (diversifies bureau hits). No AF."),

    # ── USAA ─────────────────────────────────────────────────────────

    _P(lender="USAA", product_name="Business Visa",
       product_type="credit_card", min_score=660,
       typical_limit_low=5000, typical_limit_high=35000,
       bureau_pulled="Equifax,TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=38, category="mid_tier",
       reference_url="https://www.usaa.com/inet/wc/banking-credit-cards",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/usaa-preferred-cash-rewards",
       notes="Military/veteran only. Very generous limits. Low rates. Equifax primary pull."),

    # ── DCU (Digital Federal Credit Union) ───────────────────────────

    _P(lender="DCU", product_name="Business Visa Platinum",
       product_type="credit_card", min_score=660,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=39, category="mid_tier",
       reference_url="https://www.dcu.org/borrow/credit-cards.html",
       limit_source_url="https://www.doctorofcredit.com/dcu-visa-platinum-credit-card/",
       notes="Anyone can join ($5 to ALA). Equifax pull. Very low ongoing APR. 0% intro 12mo."),

    # ── Alliant Credit Union ─────────────────────────────────────────

    _P(lender="Alliant", product_name="Business Visa Platinum",
       product_type="credit_card", min_score=660,
       typical_limit_low=5000, typical_limit_high=30000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=40, category="mid_tier",
       reference_url="https://www.alliantcreditunion.org/bank/business-credit-card",
       limit_source_url="https://www.doctorofcredit.com/alliant-visa-platinum-credit-card/",
       notes="Anyone can join. Equifax pull. Low APR. Good for diversifying bureau hits."),

    # ── SchoolsFirst FCU ─────────────────────────────────────────────

    _P(lender="SchoolsFirst FCU", product_name="Business Visa",
       product_type="credit_card", min_score=650,
       typical_limit_low=5000, typical_limit_high=25000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=6,
       annual_fee=0, recommended_order=41, category="mid_tier",
       reference_url="https://www.schoolsfirstfcu.org/wps/portal/business/credit-cards",
       limit_source_url="https://www.nerdwallet.com/article/banking/schoolsfirst-federal-credit-union-review",
       notes="CA educators/school employees. Equifax only. Known for generous limits."),

    # ── First Tech FCU ───────────────────────────────────────────────

    _P(lender="First Tech FCU", product_name="Business Rewards Visa",
       product_type="credit_card", min_score=670,
       typical_limit_low=5000, typical_limit_high=25000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=42, category="mid_tier",
       reference_url="https://www.firsttechfed.com/borrow/credit-cards",
       limit_source_url="https://www.doctorofcredit.com/first-tech-federal-credit-union-review/",
       notes="Join via Computer History Museum ($50). Equifax pull. 0% intro 12mo. Low ongoing APR."),

    # ── Lake Michigan Credit Union ───────────────────────────────────

    _P(lender="Lake Michigan CU", product_name="Business Visa Platinum",
       product_type="credit_card", min_score=660,
       typical_limit_low=5000, typical_limit_high=25000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=43, category="mid_tier",
       reference_url="https://www.lmcu.org/business/credit-cards/",
       limit_source_url="https://www.doctorofcredit.com/lake-michigan-credit-union-review/",
       notes="West MI or join via ALA ($5). Equifax pull. Low rates. 0% intro."),

    # ── Connexus Credit Union ────────────────────────────────────────

    _P(lender="Connexus CU", product_name="Business Visa",
       product_type="credit_card", min_score=660,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=44, category="mid_tier",
       reference_url="https://www.connexuscu.org/business/credit-cards/",
       limit_source_url="https://www.nerdwallet.com/article/banking/connexus-credit-union-review",
       notes="Join via Connexus Association ($5). TransUnion pull. Competitive rates."),

    # ── Andrews FCU ──────────────────────────────────────────────────

    _P(lender="Andrews FCU", product_name="Business Visa Platinum",
       product_type="credit_card", min_score=660,
       typical_limit_low=5000, typical_limit_high=25000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=6,
       annual_fee=0, recommended_order=45, category="mid_tier",
       reference_url="https://www.andrewsfcu.org/borrow/credit-cards",
       limit_source_url="https://www.nerdwallet.com/article/banking/andrews-federal-credit-union-review",
       notes="Membership via World Council donation. Equifax pull. Low rates."),

    # ── Pentagon FCU (PenFed) — PERSONAL LOC ONLY (no business LOC product) ──

    _P(lender="PenFed", product_name="Personal Line of Credit",
       product_type="loc", min_score=660,
       typical_limit_low=500, typical_limit_high=50000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=55, category="mid_tier",
       docs_level="moderate", startup_grade=None, min_time_months=None, max_line=50000,
       reference_url="https://www.penfed.org/personal-loans/personal-line-of-credit",
       limit_source_url="https://www.nerdwallet.com/article/banking/penfed-credit-union-review",
       notes="PERSONAL only — PenFed has no business LOC product. Anyone can join via $5 donation."),

    # ═════════════════════════════════════════════════════════════════
    # NEOBANKS / FINTECH — NO PERSONAL CREDIT PULL
    # ═════════════════════════════════════════════════════════════════

    _P(lender="Brex", product_name="Brex Card",
       product_type="credit_card", min_score=None,
       typical_limit_low=5000, typical_limit_high=100000,
       bureau_pulled="none", inquiry_sensitive=False,
       personal_guarantee=False, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=50, category="starter",
       reference_url="https://www.brex.com/product/business-card",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/brex-card-for-startups",
       notes="No personal credit check. No PG. Limit based on bank balance. Need $50k+ in business bank."),

    _P(lender="Ramp", product_name="Ramp Corporate Card",
       product_type="credit_card", min_score=None,
       typical_limit_low=5000, typical_limit_high=500000,
       bureau_pulled="none", inquiry_sensitive=False,
       personal_guarantee=False, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=51, category="starter",
       reference_url="https://ramp.com/cards",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/ramp-card",
       notes="No personal credit check. No PG. 1.5% cashback. Limit = business bank balance."),

    _P(lender="Divvy (Bill.com)", product_name="Divvy Business Card",
       product_type="credit_card", min_score=None,
       typical_limit_low=1000, typical_limit_high=100000,
       bureau_pulled="soft_pull", inquiry_sensitive=False,
       personal_guarantee=False, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=52, category="starter",
       reference_url="https://www.bill.com/product/spend-and-expense",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/divvy-credit-card",
       notes="Soft pull only. No PG. Built-in budgets/expense mgmt. Pay weekly/biweekly/monthly."),

    _P(lender="Stripe", product_name="Corporate Card",
       product_type="credit_card", min_score=None,
       typical_limit_low=5000, typical_limit_high=200000,
       bureau_pulled="none", inquiry_sensitive=False,
       personal_guarantee=False, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=53, category="starter",
       reference_url="https://stripe.com/issuing",
       limit_source_url="https://www.nerdwallet.com/article/small-business/stripe-corporate-card",
       notes="For Stripe merchants. Limit based on processing volume. No PG. 1.5% cashback."),

    _P(lender="Mercury", product_name="IO Business Card",
       product_type="credit_card", min_score=None,
       typical_limit_low=5000, typical_limit_high=200000,
       bureau_pulled="soft_pull", inquiry_sensitive=False,
       personal_guarantee=False, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=54, category="starter",
       reference_url="https://mercury.com/io",
       limit_source_url="https://www.nerdwallet.com/article/banking/mercury-bank-review",
       notes="Startup-focused. Soft pull only. 1.5% cashback. Limit based on deposits."),

    # ═════════════════════════════════════════════════════════════════
    # BUSINESS LINES OF CREDIT
    # ═════════════════════════════════════════════════════════════════

    # ── Startup-Friendly LOCs (sorted by startup grade) ──────────────

    _P(lender="Fundbox", product_name="Business Line of Credit",
       product_type="loc", min_score=600,
       typical_limit_low=1000, typical_limit_high=150000,
       bureau_pulled="soft_pull", inquiry_sensitive=False,
       personal_guarantee=False, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=55, category="starter",
       docs_level="very_low", startup_grade="A+", min_time_months=3, max_line=150000,
       reference_url="https://fundbox.com/line-of-credit/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/fundbox-review",
       notes="BEST FOR STARTUPS. Soft pull only. Connect bank account — no tax returns."
             " 3-month min. 12-24 week repayment."),

    _P(lender="StartCap", product_name="Startup Business Line of Credit",
       product_type="loc", min_score=650,
       typical_limit_low=10000, typical_limit_high=250000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=56, category="starter",
       docs_level="very_low", startup_grade="A+", min_time_months=0, max_line=250000,
       reference_url="https://www.startcap.org/start-up-business-loans/line-of-credit",
       limit_source_url="https://www.nerdwallet.com/best/small-business/startup-business-loans",
       notes="DAY-1 STARTUPS WELCOME. No revenue required. No business plan needed."
             " Personal credit is primary factor."),

    _P(lender="Credibly", product_name="Business Line of Credit",
       product_type="loc", min_score=675,
       typical_limit_low=5000, typical_limit_high=250000,
       bureau_pulled="TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=57, category="mid_tier",
       docs_level="low", startup_grade="B+", min_time_months=6, max_line=250000,
       reference_url="https://www.credibly.com/business-line-of-credit/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/credibly-review",
       notes="6-month min. Bank statements + ID only. $15k/mo avg deposits. Fast approval."),

    _P(lender="Headway Capital", product_name="Business Line of Credit",
       product_type="loc", min_score=620,
       typical_limit_low=5000, typical_limit_high=100000,
       bureau_pulled="TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=58, category="mid_tier",
       docs_level="moderate", startup_grade="B", min_time_months=6, max_line=100000,
       reference_url="https://www.headwaycapital.com/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/headway-capital-review",
       notes="6-12 month min. Bank statements + ID. $50k annual revenue. 12-24 month terms."),

    # ── Traditional LOCs (12+ months in business) ─────────────────

    _P(lender="Kabbage (Amex)", product_name="Business Line of Credit",
       product_type="loc", min_score=640,
       typical_limit_low=2000, typical_limit_high=150000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=60, category="mid_tier",
       docs_level="low", startup_grade="C+", min_time_months=12, max_line=250000,
       reference_url="https://www.kabbage.com/line-of-credit/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/kabbage-review",
       notes="12-month min. Automated approval via bank data. $3k/mo revenue. 6-18 month terms."),

    _P(lender="American Express", product_name="Business Line of Credit",
       product_type="loc", min_score=640,
       typical_limit_low=2000, typical_limit_high=250000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=61, category="mid_tier",
       docs_level="low", startup_grade="C+", min_time_months=12, max_line=250000,
       reference_url="https://www.americanexpress.com/en-us/business/loans-and-financing/business-line-of-credit/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/american-express-business-line-of-credit",
       notes="12-month min. $36k annual revenue. 6-24 month terms. Weekly/monthly payments."),

    _P(lender="Bluevine", product_name="Business Line of Credit",
       product_type="loc", min_score=625,
       typical_limit_low=5000, typical_limit_high=250000,
       bureau_pulled="Experian,TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=62, category="mid_tier",
       docs_level="low", startup_grade="C", min_time_months=12, max_line=250000,
       reference_url="https://www.bluevine.com/line-of-credit/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/bluevine-line-of-credit-review",
       notes="12-month min. $120k annual revenue. Link bank account — no tax returns. 6-12 month terms."),

    _P(lender="Lendio", product_name="LOC Marketplace",
       product_type="loc", min_score=600,
       typical_limit_low=5000, typical_limit_high=500000,
       bureau_pulled="soft_pull", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=63, category="mid_tier",
       docs_level="low", startup_grade="B", min_time_months=6, max_line=500000,
       reference_url="https://www.lendio.com/business-line-of-credit/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/lendio-review",
       notes="MARKETPLACE — matches with 75+ lenders. Some accept startups. Soft pull for prequal."),

    # ── Big Bank LOCs (2+ years, heavy docs) ──────────────────────

    _P(lender="Wells Fargo", product_name="Small Business Advantage LOC",
       product_type="loc", min_score=680,
       typical_limit_low=5000, typical_limit_high=50000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=64, category="mid_tier",
       docs_level="high", startup_grade="B+", min_time_months=6, max_line=50000,
       reference_url="https://www.wellsfargo.com/biz/loans-and-lines/lines-of-credit/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/wells-fargo-small-business-line-of-credit",
       notes="EXPLICIT STARTUP PRODUCT for <2yr businesses. Tax returns + financials required. $50k cap."),

    _P(lender="Wells Fargo", product_name="BusinessLine LOC",
       product_type="loc", min_score=680,
       typical_limit_low=10000, typical_limit_high=150000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=65, category="mid_tier",
       docs_level="high", startup_grade="D", min_time_months=24, max_line=150000,
       reference_url="https://www.wellsfargo.com/biz/loans-and-lines/lines-of-credit/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/wells-fargo-small-business-line-of-credit",
       notes="2-year min. Standard LOC for established businesses. Tax returns + financials required."),

    _P(lender="Chase", product_name="Business Line of Credit",
       product_type="loc", min_score=680,
       typical_limit_low=5000, typical_limit_high=500000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=66, category="premium",
       docs_level="high", startup_grade="D", min_time_months=24, max_line=500000,
       reference_url="https://www.chase.com/business/loans/lines-of-credit",
       limit_source_url="https://www.nerdwallet.com/article/small-business/chase-business-line-of-credit",
       notes="2-year min STRICT. Tax returns + financials. Existing Chase relationship helps."),

    _P(lender="Bank of America", product_name="Business Advantage LOC",
       product_type="loc", min_score=680,
       typical_limit_low=10000, typical_limit_high=250000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=67, category="premium",
       docs_level="high", startup_grade="D", min_time_months=24, max_line=250000,
       reference_url="https://www.bankofamerica.com/smallbusiness/business-financing/business-line-of-credit/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/bank-of-america-business-line-of-credit",
       notes="2-year min. $250k+ annual revenue. Tax returns + financials. Preferred Rewards pricing."),

    _P(lender="Bank of America", product_name="Cash-Secured Business LOC",
       product_type="loc", min_score=700,
       typical_limit_low=1000, typical_limit_high=100000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=68, category="starter",
       docs_level="moderate", startup_grade="B-", min_time_months=6, max_line=100000,
       reference_url="https://www.bankofamerica.com/smallbusiness/business-financing/cash-secured-business-line-of-credit/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/bank-of-america-business-line-of-credit",
       notes="6-month min. Borrow against your deposit. Graduation path to unsecured after 1 year."),

    _P(lender="Navy Federal", product_name="Business Line of Credit",
       product_type="loc", min_score=650,
       typical_limit_low=5000, typical_limit_high=100000,
       bureau_pulled="TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=325, recommended_order=69, category="mid_tier",
       docs_level="high", startup_grade="D", min_time_months=24, max_line=100000,
       reference_url="https://www.navyfederal.org/loans-cards/business-loans/business-line-of-credit.html",
       limit_source_url="https://www.nerdwallet.com/article/small-business/navy-federal-business-line-of-credit",
       notes="Military/DOD only. 24-36 month est. min. $325/yr fee. Collateral required. Competitive rates."),

    # ═════════════════════════════════════════════════════════════════
    # TERM LOANS
    # ═════════════════════════════════════════════════════════════════

    _P(lender="OnDeck", product_name="Term Loan",
       product_type="term_loan", min_score=625,
       typical_limit_low=5000, typical_limit_high=250000,
       bureau_pulled="Experian,TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=70, category="mid_tier",
       reference_url="https://www.ondeck.com/business-term-loan",
       limit_source_url="https://www.nerdwallet.com/article/small-business/ondeck-review",
       notes="Fixed-term business loan. 18-month terms. Requires $100k+ annual revenue."),

    _P(lender="Funding Circle", product_name="Business Term Loan",
       product_type="term_loan", min_score=660,
       typical_limit_low=25000, typical_limit_high=500000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=71, category="premium",
       reference_url="https://www.fundingcircle.com/us/small-business-loans/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/funding-circle-review",
       notes="SBA-style terms from marketplace lender. 6 months - 7 years."),

    _P(lender="Lendio", product_name="Business Loan Marketplace",
       product_type="term_loan", min_score=600,
       typical_limit_low=5000, typical_limit_high=500000,
       bureau_pulled="soft_pull", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=72, category="mid_tier",
       reference_url="https://www.lendio.com/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/lendio-review",
       notes="Marketplace — matches you with 75+ lenders. Soft pull for prequalification."),

    _P(lender="BlueVine", product_name="Term Loan",
       product_type="term_loan", min_score=650,
       typical_limit_low=6000, typical_limit_high=250000,
       bureau_pulled="Experian,TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=73, category="mid_tier",
       reference_url="https://www.bluevine.com/term-loan/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/bluevine-line-of-credit-review",
       notes="Fixed payments. 26-52 week terms. $480k+ annual revenue requirement."),

    _P(lender="National Funding", product_name="Working Capital Loan",
       product_type="term_loan", min_score=600,
       typical_limit_low=5000, typical_limit_high=500000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=74, category="mid_tier",
       reference_url="https://www.nationalfunding.com/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/national-funding-review",
       notes="Working capital and equipment loans. Lower credit requirements. Same-day funding available."),

    _P(lender="Biz2Credit", product_name="Working Capital Loan",
       product_type="term_loan", min_score=575,
       typical_limit_low=25000, typical_limit_high=2000000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=75, category="mid_tier",
       reference_url="https://www.biz2credit.com/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/biz2credit-review",
       notes="Low credit requirement. Fast approval. Higher cost but accessible."),

    _P(lender="Credibly", product_name="Business Loan",
       product_type="term_loan", min_score=500,
       typical_limit_low=5000, typical_limit_high=400000,
       bureau_pulled="soft_pull", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=76, category="starter",
       reference_url="https://www.credibly.com/business-loans/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/credibly-review",
       notes="Very low score requirement. Revenue-based underwriting. 3-24 month terms."),

    # ═════════════════════════════════════════════════════════════════
    # SBA LOANS
    # ═════════════════════════════════════════════════════════════════

    _P(lender="SBA", product_name="7(a) Microloan",
       product_type="sba", min_score=650,
       typical_limit_low=500, typical_limit_high=50000,
       bureau_pulled="Experian,TransUnion,Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=80, category="mid_tier",
       reference_url="https://www.sba.gov/funding-programs/loans/microloans",
       limit_source_url="https://www.sba.gov/funding-programs/loans/microloans",
       notes="Government-backed via nonprofit intermediaries. 6-year max term. Lowest rates available."),

    _P(lender="SBA", product_name="7(a) Standard Loan",
       product_type="sba", min_score=680,
       typical_limit_low=50000, typical_limit_high=5000000,
       bureau_pulled="Experian,TransUnion,Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=81, category="premium",
       reference_url="https://www.sba.gov/funding-programs/loans/7a-loans",
       limit_source_url="https://www.sba.gov/funding-programs/loans/7a-loans",
       notes="Full SBA 7(a). Prime + 2.25-4.75%. 10-25 year terms. Requires business plan."),

    _P(lender="SBA", product_name="Community Advantage",
       product_type="sba", min_score=620,
       typical_limit_low=50000, typical_limit_high=350000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=82, category="starter",
       reference_url="https://www.sba.gov/funding-programs/loans/7a-loans",
       limit_source_url="https://www.sba.gov/funding-programs/loans/7a-loans",
       notes="SBA program for underserved communities. Lower score requirements."),

    _P(lender="SBA", product_name="504 Loan",
       product_type="sba", min_score=680,
       typical_limit_low=125000, typical_limit_high=5500000,
       bureau_pulled="Experian,TransUnion,Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=83, category="premium",
       reference_url="https://www.sba.gov/funding-programs/loans/504-loans",
       limit_source_url="https://www.sba.gov/funding-programs/loans/504-loans",
       notes="Fixed assets (real estate, equipment). Below-market fixed rate. 10-25 year terms."),

    _P(lender="SmartBiz", product_name="SBA 7(a) Loan",
       product_type="sba", min_score=650,
       typical_limit_low=30000, typical_limit_high=350000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=84, category="mid_tier",
       reference_url="https://www.smartbizloans.com/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/smartbiz-loans-review",
       notes="Streamlined SBA application process. Faster than traditional SBA. Bank-partner model."),

    _P(lender="Live Oak Bank", product_name="SBA 7(a) Loan",
       product_type="sba", min_score=680,
       typical_limit_low=100000, typical_limit_high=5000000,
       bureau_pulled="Experian,Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=85, category="premium",
       reference_url="https://www.liveoakbank.com/small-business-loans/",
       limit_source_url="https://www.nerdwallet.com/article/small-business/live-oak-bank-sba-loans",
       notes="#1 SBA lender by volume. Industry-specific expertise. Fully digital process."),

    # ═════════════════════════════════════════════════════════════════
    # 0% APR / BALANCE TRANSFER STRATEGIES
    # ═════════════════════════════════════════════════════════════════

    _P(lender="US Bank", product_name="Business Triple Cash (0% APR)",
       product_type="balance_transfer", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=15,
       annual_fee=0, recommended_order=90, category="mid_tier",
       reference_url="https://www.usbank.com/credit-cards/business-triple-cash-rewards-visa-business-card.html",
       limit_source_url="https://www.doctorofcredit.com/us-bank-business-triple-cash-rewards/",
       notes="LONGEST 0% intro at 15 months. Best for float/working capital strategy."),

    _P(lender="Amex", product_name="Blue Business Plus (0% APR)",
       product_type="balance_transfer", min_score=660,
       typical_limit_low=5000, typical_limit_high=25000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=91, category="mid_tier",
       reference_url="https://www.americanexpress.com/us/credit-cards/business/business-credit-cards/blue-business-plus-credit-card-amex/",
       limit_source_url="https://www.doctorofcredit.com/american-express-blue-business-plus/",
       notes="0% intro 12 months on purchases. Good for float. 2x MR points."),

    _P(lender="Chase", product_name="Ink Business Unlimited (0% APR)",
       product_type="balance_transfer", min_score=680,
       typical_limit_low=3000, typical_limit_high=35000,
       bureau_pulled="Experian", inquiry_sensitive=True,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=92, category="mid_tier",
       reference_url="https://creditcards.chase.com/business-credit-cards/ink/business-unlimited",
       limit_source_url="https://www.doctorofcredit.com/chase-ink-business-unlimited/",
       notes="0% intro 12 months. Subject to 5/24. 1.5% cashback."),

    _P(lender="Capital One", product_name="Spark Cash Select (0% APR)",
       product_type="balance_transfer", min_score=660,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="TransUnion,Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=93, category="mid_tier",
       reference_url="https://www.capitalone.com/small-business/credit-cards/spark-cash-select/",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/capital-one-spark-cash-select",
       notes="0% intro 12 months. 1.5% cashback. TransUnion primary pull."),

    _P(lender="Wells Fargo", product_name="Signify Business Cash (0% APR)",
       product_type="balance_transfer", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=94, category="mid_tier",
       reference_url="https://www.wellsfargo.com/biz/business-credit/credit-cards/signify-business-cash-card/",
       limit_source_url="https://www.doctorofcredit.com/wells-fargo-signify-business-cash/",
       notes="0% intro 12 months. 2% unlimited cashback."),

    _P(lender="Bank of America", product_name="Business Advantage (0% APR)",
       product_type="balance_transfer", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Experian", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=9,
       annual_fee=0, recommended_order=95, category="mid_tier",
       reference_url="https://www.bankofamerica.com/smallbusiness/credit-cards/business-advantage-customized-cash-rewards/",
       limit_source_url="https://www.doctorofcredit.com/bank-of-america-business-advantage-customized-cash/",
       notes="0% intro 9 months. Shortest intro period but strong relationship pricing."),

    # ═════════════════════════════════════════════════════════════════
    # STORE / VENDOR BUSINESS CREDIT (No personal pull or Net terms)
    # ═════════════════════════════════════════════════════════════════

    _P(lender="Uline", product_name="Business Net-30 Account",
       product_type="loc", min_score=None,
       typical_limit_low=500, typical_limit_high=5000,
       bureau_pulled="none", inquiry_sensitive=False,
       personal_guarantee=False, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=100, category="starter",
       reference_url="https://www.uline.com/",
       limit_source_url="https://www.nav.com/business-credit-cards/uline-net-30-account/",
       notes="Net-30 trade credit. Reports to D&B. No personal credit check. Build business credit."),

    _P(lender="Grainger", product_name="Business Net-30 Account",
       product_type="loc", min_score=None,
       typical_limit_low=500, typical_limit_high=10000,
       bureau_pulled="none", inquiry_sensitive=False,
       personal_guarantee=False, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=101, category="starter",
       reference_url="https://www.grainger.com/content/credit-services",
       limit_source_url="https://www.nav.com/business-credit-cards/grainger-net-30-account/",
       notes="Net-30 trade credit. Reports to D&B. No personal credit check. Industrial supplies."),

    _P(lender="Quill (Staples)", product_name="Business Net-30 Account",
       product_type="loc", min_score=None,
       typical_limit_low=500, typical_limit_high=5000,
       bureau_pulled="none", inquiry_sensitive=False,
       personal_guarantee=False, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=102, category="starter",
       reference_url="https://www.quill.com/content/index/credit/credit.cshtml",
       limit_source_url="https://www.nav.com/business-credit-cards/quill-net-30-account/",
       notes="Net-30 trade credit. Reports to D&B. Office supplies. Easy approval."),

    _P(lender="Amazon Business", product_name="Business Line of Credit",
       product_type="loc", min_score=None,
       typical_limit_low=1000, typical_limit_high=100000,
       bureau_pulled="none", inquiry_sensitive=False,
       personal_guarantee=False, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=103, category="starter",
       reference_url="https://www.amazon.com/gp/cobrandcard/marketing.html?pr=ibprec",
       limit_source_url="https://www.nerdwallet.com/article/small-business/amazon-business-line-of-credit",
       notes="Pay-by-invoice with Net-30/60/90 terms. No personal credit check. Reports to D&B."),

    _P(lender="Home Depot Pro", product_name="Business Net-30 Account",
       product_type="loc", min_score=None,
       typical_limit_low=500, typical_limit_high=10000,
       bureau_pulled="none", inquiry_sensitive=False,
       personal_guarantee=False, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=104, category="starter",
       reference_url="https://www.homedepot.com/c/pro_xtra_credit",
       limit_source_url="https://www.nav.com/business-credit-cards/home-depot-commercial-account/",
       notes="Pro account with Net-30. Reports to D&B. Good for contractors/construction."),

    # ═════════════════════════════════════════════════════════════════
    # ADDITIONAL BUSINESS CREDIT CARDS — SPECIALTY
    # ═════════════════════════════════════════════════════════════════

    _P(lender="Sam's Club", product_name="Business Mastercard",
       product_type="credit_card", min_score=660,
       typical_limit_low=3000, typical_limit_high=20000,
       bureau_pulled="TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=32, category="mid_tier",
       reference_url="https://www.samsclub.com/content/credit",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/sams-club-business-mastercard",
       notes="5% gas (up to $6k), 3% dining/travel, 1% all else. 0% intro 12mo. Sam's membership req."),

    _P(lender="Truist", product_name="Business Cash Rewards",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Equifax,TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=33, category="mid_tier",
       reference_url="https://www.truist.com/small-business/credit-cards",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/truist-business-cash-rewards",
       notes="Regional major bank. Equifax primary pull. 3% chosen category, 2% gas/dining."),

    _P(lender="TD Bank", product_name="Business Solutions Credit Card",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=9,
       annual_fee=0, recommended_order=34, category="mid_tier",
       reference_url="https://www.td.com/us/en/small-business/credit-cards/",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/td-business-solutions",
       notes="East coast regional. TransUnion pull. 0% intro 9 months."),

    _P(lender="PNC", product_name="Business Options Visa",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=9,
       annual_fee=0, recommended_order=34, category="mid_tier",
       reference_url="https://www.pnc.com/en/small-business/borrowing/business-credit-cards.html",
       limit_source_url="https://www.nerdwallet.com/reviews/credit-cards/pnc-business-options-visa",
       notes="Mid-Atlantic/Midwest. Equifax primary pull. 0% intro 9 months."),

    _P(lender="Citizens Bank", product_name="Business Platinum Visa",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=9,
       annual_fee=0, recommended_order=34, category="mid_tier",
       reference_url="https://www.citizensbank.com/small-business/credit-cards.aspx",
       limit_source_url="https://www.nerdwallet.com/article/small-business/citizens-bank-business-credit-card",
       notes="Northeast/Mid-Atlantic. Equifax pull. 0% intro 9 months."),

    _P(lender="Huntington Bank", product_name="Business Rewards Visa",
       product_type="credit_card", min_score=670,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=34, category="mid_tier",
       reference_url="https://www.huntington.com/business/credit-cards",
       limit_source_url="https://www.nerdwallet.com/article/small-business/huntington-bank-business-credit-card",
       notes="Midwest regional. Equifax pull. Good for diversifying bureau exposure."),

    _P(lender="Fifth Third Bank", product_name="Business Real Life Rewards",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=12,
       annual_fee=0, recommended_order=34, category="mid_tier",
       reference_url="https://www.53.com/content/fifth-third/en/business-banking/credit-cards.html",
       limit_source_url="https://www.nerdwallet.com/article/small-business/fifth-third-bank-business-credit-card",
       notes="Midwest/Southeast. Equifax pull. 0% intro 12 months. 1.67% cashback on all."),

    _P(lender="Regions Bank", product_name="Business Visa",
       product_type="credit_card", min_score=670,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=0.0, intro_period_months=9,
       annual_fee=0, recommended_order=34, category="mid_tier",
       reference_url="https://www.regions.com/small-business/credit-cards",
       limit_source_url="https://www.nerdwallet.com/article/small-business/regions-bank-business-credit-card",
       notes="Southeast/Midwest. Equifax pull. Good for Equifax bureau diversity."),

    _P(lender="KeyBank", product_name="Business Rewards Mastercard",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="TransUnion", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=34, category="mid_tier",
       reference_url="https://www.key.com/small-business/credit-cards/index.html",
       limit_source_url="https://www.nerdwallet.com/article/small-business/keybank-business-credit-card",
       notes="Northeast/Midwest. TransUnion pull. Relationship pricing benefits."),

    _P(lender="M&T Bank", product_name="Business Credit Card",
       product_type="credit_card", min_score=680,
       typical_limit_low=3000, typical_limit_high=25000,
       bureau_pulled="Equifax", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=34, category="mid_tier",
       reference_url="https://www.mtb.com/business/credit-cards",
       limit_source_url="https://www.nerdwallet.com/article/small-business/m-and-t-bank-business-credit-card",
       notes="Northeast. Equifax pull. Known for business-friendly underwriting."),

    # ═════════════════════════════════════════════════════════════════
    # HIGH-COMMISSION REFERRAL PRODUCTS (NEW)
    # ═════════════════════════════════════════════════════════════════

    _P(lender="Greenbox Capital", product_name="Business MCA / Short-Term Loan",
       product_type="term_loan", min_score=500,
       typical_limit_low=5000, typical_limit_high=500000,
       bureau_pulled="Soft Pull", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=90, category="mid_tier",
       docs_level="low", startup_grade="B", min_time_months=6, max_line=500000,
       notes="MCA / short-term. ISO program pays 15-19% commission. Fast funding 24-48hrs."),

    _P(lender="ARF Financial", product_name="Business Term Loan",
       product_type="term_loan", min_score=550,
       typical_limit_low=5000, typical_limit_high=150000,
       bureau_pulled="Soft Pull", inquiry_sensitive=False,
       personal_guarantee=True, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=91, category="mid_tier",
       docs_level="low", startup_grade="B-", min_time_months=6, max_line=150000,
       notes="Direct referral program pays 8% commission. 3-18 month terms."),

    _P(lender="Credit Suite", product_name="Business Credit Building Program",
       product_type="loc", min_score=0,
       typical_limit_low=0, typical_limit_high=150000,
       bureau_pulled="None", inquiry_sensitive=False,
       personal_guarantee=False, intro_apr=None, intro_period_months=None,
       annual_fee=0, recommended_order=92, category="starter",
       docs_level="very_low", startup_grade="A+", min_time_months=0, max_line=150000,
       notes="Business credit building. Affiliate program pays per signup. No PG required."),
]


# ═══════════════════════════════════════════════════════════════════════
# LENDER TYPE CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════

_LENDER_TYPES = {
    # Banks
    "Bank of America": "bank", "Capital One": "bank", "Chase": "bank",
    "Citi": "bank", "Citizens Bank": "bank", "Fifth Third Bank": "bank",
    "Huntington Bank": "bank", "KeyBank": "bank", "Live Oak Bank": "bank",
    "M&T Bank": "bank", "PNC": "bank", "Regions Bank": "bank",
    "TD Bank": "bank", "Truist": "bank", "US Bank": "bank",
    "Wells Fargo": "bank", "Amex": "bank", "American Express": "bank",
    "Sam's Club": "bank",  # issued by Synchrony Bank

    # Credit Unions
    "Alliant": "credit_union", "Andrews FCU": "credit_union",
    "Connexus CU": "credit_union", "DCU": "credit_union",
    "First Tech FCU": "credit_union", "Lake Michigan CU": "credit_union",
    "Navy Federal": "credit_union", "PenFed": "credit_union",
    "SchoolsFirst FCU": "credit_union", "USAA": "credit_union",

    # Fintech
    "BlueVine": "fintech", "Bluevine": "fintech", "Brex": "fintech",
    "Divvy (Bill.com)": "fintech", "Fundbox": "fintech",
    "Headway Capital": "fintech", "Kabbage (Amex)": "fintech",
    "Mercury": "fintech", "OnDeck": "fintech", "Ramp": "fintech",
    "StartCap": "fintech", "Stripe": "fintech",
    "Amazon Business": "fintech",

    # Marketplace / Brokers
    "Biz2Credit": "marketplace", "Credibly": "marketplace",
    "Funding Circle": "marketplace", "Lendio": "marketplace",
    "National Funding": "marketplace", "SmartBiz": "marketplace",

    # Vendor / Net-30
    "Grainger": "vendor", "Home Depot Pro": "vendor",
    "Quill (Staples)": "vendor", "Uline": "vendor",

    # Government
    "SBA": "government",
}

# Apply lender_type to all products
for _prod in PRODUCTS:
    if _prod.lender_type is None:
        _prod.lender_type = _LENDER_TYPES.get(_prod.lender)


# ═══════════════════════════════════════════════════════════════════════
# REFERRAL COMMISSION DATA
# ═══════════════════════════════════════════════════════════════════════
# Key: (lender, product_name) → referral fields
# commission_type: percentage / flat_fee / points / recurring

_REFERRAL_DATA = {
    # ── Tier 1: High Commission (ISO/Broker, 5-19%) ──────────────────

    ("Greenbox Capital", "Business MCA / Short-Term Loan"): {
        "has_referral": True, "referral_commission_type": "percentage",
        "referral_commission_value": 17.0,
        "referral_commission_display": "15-19% of funded amount (ISO program)",
        "referral_requires_license": False,
    },
    ("ARF Financial", "Business Term Loan"): {
        "has_referral": True, "referral_commission_type": "percentage",
        "referral_commission_value": 8.0,
        "referral_commission_display": "8% of funded amount",
        "referral_requires_license": False,
    },
    ("National Funding", "Working Capital Loan"): {
        "has_referral": True, "referral_commission_type": "percentage",
        "referral_commission_value": 3.0,
        "referral_commission_display": "3% of funded amount",
        "referral_requires_license": False,
    },
    ("OnDeck", "Term Loan"): {
        "has_referral": True, "referral_commission_type": "percentage",
        "referral_commission_value": 2.0,
        "referral_commission_display": "2% of funded amount (ISO/referral)",
        "referral_requires_license": False,
    },
    ("Credibly", "Business Line of Credit"): {
        "has_referral": True, "referral_commission_type": "percentage",
        "referral_commission_value": 4.0,
        "referral_commission_display": "3-5% agent commission",
        "referral_requires_license": False,
    },
    ("Credibly", "Business Loan"): {
        "has_referral": True, "referral_commission_type": "percentage",
        "referral_commission_value": 4.0,
        "referral_commission_display": "3-5% agent commission",
        "referral_requires_license": False,
    },
    ("Biz2Credit", "Working Capital Loan"): {
        "has_referral": True, "referral_commission_type": "flat_fee",
        "referral_commission_value": 200.0,
        "referral_commission_display": "$200 per funded deal",
        "referral_requires_license": False,
    },
    ("Kabbage (Amex)", "Business Line of Credit"): {
        "has_referral": True, "referral_commission_type": "flat_fee",
        "referral_commission_value": 200.0,
        "referral_commission_display": "$200 per funded deal",
        "referral_requires_license": False,
    },

    # ── Tier 2: Mid Commission (Partner programs, 2-5%) ──────────────

    ("SBA", "7(a) Microloan"): {
        "has_referral": True, "referral_commission_type": "percentage",
        "referral_commission_value": 2.0,
        "referral_commission_display": "2% referral agent fee (SBA Form 159)",
        "referral_requires_license": True,
    },
    ("SBA", "7(a) Standard Loan"): {
        "has_referral": True, "referral_commission_type": "percentage",
        "referral_commission_value": 2.0,
        "referral_commission_display": "2% referral agent fee (SBA Form 159)",
        "referral_requires_license": True,
    },
    ("SBA", "Community Advantage"): {
        "has_referral": True, "referral_commission_type": "percentage",
        "referral_commission_value": 2.0,
        "referral_commission_display": "2% referral agent fee (SBA Form 159)",
        "referral_requires_license": True,
    },
    ("SBA", "504 Loan"): {
        "has_referral": True, "referral_commission_type": "percentage",
        "referral_commission_value": 2.0,
        "referral_commission_display": "2% referral agent fee (SBA Form 159)",
        "referral_requires_license": True,
    },
    ("StartCap", "Startup Business Line of Credit"): {
        "has_referral": True, "referral_commission_type": "percentage",
        "referral_commission_value": 2.0,
        "referral_commission_display": "2% of funded amount",
        "referral_requires_license": False,
    },
    ("Ramp", "Ramp Corporate Card"): {
        "has_referral": True, "referral_commission_type": "recurring",
        "referral_commission_value": 5.0,
        "referral_commission_display": "5% of first-year card spend (recurring)",
        "referral_requires_license": False,
    },
    ("Mercury", "IO Business Card"): {
        "has_referral": True, "referral_commission_type": "flat_fee",
        "referral_commission_value": 250.0,
        "referral_commission_display": "$250 per qualified signup",
        "referral_requires_license": False,
    },
    ("Brex", "Brex Card"): {
        "has_referral": True, "referral_commission_type": "flat_fee",
        "referral_commission_value": 250.0,
        "referral_commission_display": "$250 per qualified signup",
        "referral_requires_license": False,
    },
    ("Divvy (Bill.com)", "Divvy Business Card"): {
        "has_referral": True, "referral_commission_type": "flat_fee",
        "referral_commission_value": 100.0,
        "referral_commission_display": "$100 per qualified signup",
        "referral_requires_license": False,
    },
    ("Credit Suite", "Business Credit Building Program"): {
        "has_referral": True, "referral_commission_type": "flat_fee",
        "referral_commission_value": 150.0,
        "referral_commission_display": "$150 per signup (affiliate program)",
        "referral_requires_license": False,
    },

    # ── Tier 3: Points / Low Commission ──────────────────────────────

    ("Amex", "Business Gold Card"): {
        "has_referral": True, "referral_commission_type": "points",
        "referral_commission_value": 40000.0,
        "referral_commission_display": "40K Membership Rewards pts (~$400)",
        "referral_requires_license": False,
    },
    ("Amex", "Business Platinum Card"): {
        "has_referral": True, "referral_commission_type": "points",
        "referral_commission_value": 45000.0,
        "referral_commission_display": "45K Membership Rewards pts (~$450)",
        "referral_requires_license": False,
    },
    ("Amex", "Blue Business Plus"): {
        "has_referral": True, "referral_commission_type": "points",
        "referral_commission_value": 20000.0,
        "referral_commission_display": "20K Membership Rewards pts (~$200)",
        "referral_requires_license": False,
    },
    ("Amex", "Blue Business Cash"): {
        "has_referral": True, "referral_commission_type": "points",
        "referral_commission_value": 20000.0,
        "referral_commission_display": "20K Membership Rewards pts (~$200)",
        "referral_requires_license": False,
    },
    ("Amex", "Blue Business Plus (0% APR)"): {
        "has_referral": True, "referral_commission_type": "points",
        "referral_commission_value": 20000.0,
        "referral_commission_display": "20K Membership Rewards pts (~$200)",
        "referral_requires_license": False,
    },
    ("Chase", "Ink Business Preferred"): {
        "has_referral": True, "referral_commission_type": "points",
        "referral_commission_value": 20000.0,
        "referral_commission_display": "20K Ultimate Rewards pts (~$250)",
        "referral_requires_license": False,
    },
    ("Chase", "Ink Business Unlimited"): {
        "has_referral": True, "referral_commission_type": "points",
        "referral_commission_value": 20000.0,
        "referral_commission_display": "20K Ultimate Rewards pts (~$250)",
        "referral_requires_license": False,
    },
    ("Chase", "Ink Business Cash"): {
        "has_referral": True, "referral_commission_type": "points",
        "referral_commission_value": 20000.0,
        "referral_commission_display": "20K Ultimate Rewards pts (~$250)",
        "referral_requires_license": False,
    },
    ("Chase", "Ink Business Unlimited (0% APR)"): {
        "has_referral": True, "referral_commission_type": "points",
        "referral_commission_value": 20000.0,
        "referral_commission_display": "20K Ultimate Rewards pts (~$250)",
        "referral_requires_license": False,
    },
    ("Capital One", "Spark Cash Plus"): {
        "has_referral": True, "referral_commission_type": "flat_fee",
        "referral_commission_value": 200.0,
        "referral_commission_display": "$200 referral bonus",
        "referral_requires_license": False,
    },
    ("Capital One", "Spark 1.5% Cash Select"): {
        "has_referral": True, "referral_commission_type": "flat_fee",
        "referral_commission_value": 200.0,
        "referral_commission_display": "$200 referral bonus",
        "referral_requires_license": False,
    },
    ("Capital One", "Spark Cash Select (0% APR)"): {
        "has_referral": True, "referral_commission_type": "flat_fee",
        "referral_commission_value": 200.0,
        "referral_commission_display": "$200 referral bonus",
        "referral_requires_license": False,
    },
    ("Lendio", "LOC Marketplace"): {
        "has_referral": True, "referral_commission_type": "flat_fee",
        "referral_commission_value": 25.0,
        "referral_commission_display": "$25 per qualified lead",
        "referral_requires_license": False,
    },
    ("Lendio", "Business Loan Marketplace"): {
        "has_referral": True, "referral_commission_type": "flat_fee",
        "referral_commission_value": 25.0,
        "referral_commission_display": "$25 per qualified lead",
        "referral_requires_license": False,
    },
    ("Fundbox", "Business Line of Credit"): {
        "has_referral": True, "referral_commission_type": "flat_fee",
        "referral_commission_value": 50.0,
        "referral_commission_display": "$50 per funded deal",
        "referral_requires_license": False,
    },
}

# Apply referral data to matching products
for _prod in PRODUCTS:
    _key = (_prod.lender, _prod.product_name)
    if _key in _REFERRAL_DATA:
        _rdata = _REFERRAL_DATA[_key]
        _prod.has_referral = bool(_rdata.get("has_referral", False))
        _prod.referral_commission_type = _rdata.get("referral_commission_type")  # type: ignore[assignment]
        _prod.referral_commission_value = _rdata.get("referral_commission_value")  # type: ignore[assignment]
        _prod.referral_commission_display = _rdata.get("referral_commission_display")  # type: ignore[assignment]
        _prod.referral_url = _rdata.get("referral_url")  # type: ignore[assignment]
        _prod.referral_requires_license = bool(_rdata.get("referral_requires_license", False))

# Also classify the new products
for _prod in PRODUCTS:
    if _prod.lender_type is None:
        _prod.lender_type = _LENDER_TYPES.get(_prod.lender)

_LENDER_TYPES["Greenbox Capital"] = "marketplace"
_LENDER_TYPES["ARF Financial"] = "marketplace"
_LENDER_TYPES["Credit Suite"] = "fintech"

for _prod in PRODUCTS:
    if _prod.lender_type is None:
        _prod.lender_type = _LENDER_TYPES.get(_prod.lender)


def seed_catalog(db: FundingDB) -> int:
    """Seed the product catalog if empty. Returns count of products inserted."""
    if db.product_count() > 0:
        return 0

    count = 0
    for prod in PRODUCTS:
        db.save_product(prod)
        count += 1

    return count


# ═══════════════════════════════════════════════════════════════════════
# PARTNER PROGRAM SEED DATA
# ═══════════════════════════════════════════════════════════════════════

_PP = PartnerProgram

PARTNER_PROGRAMS = [
    # Priority 1 — Instant/Same-day signup
    _PP(lender="Chase", program_name="Refer-a-Friend",
        program_type="referral", commission_type="points",
        commission_display="20K Ultimate Rewards pts per approved card (~$250)",
        signup_url="https://creditcards.chase.com/refer-a-friend",
        has_api=False, priority=1,
        notes="Must hold a Chase business card. New rule (Oct 2025):"
              " referral must be NEW Chase biz card customer. Max 10/month."),

    _PP(lender="Amex", program_name="Member Referral",
        program_type="referral", commission_type="points",
        commission_display="20K-45K Membership Rewards pts per approved card (~$200-$450)",
        signup_url="https://www.americanexpress.com/en-us/referral",
        has_api=False, priority=1,
        notes="Must hold an Amex card. Bonus earned even if friend picks different card."
              " Annual caps vary by card. 1099 issued."),

    _PP(lender="Capital One", program_name="Refer-a-Business",
        program_type="referral", commission_type="flat_fee",
        commission_display="$200 per approved card",
        signup_url="https://www.capitalone.com/small-business/credit-cards/lp/refer-a-business/",
        has_api=False, priority=1,
        notes="Must hold Capital One biz card."
              " Referral cannot be existing Capital One biz cardholder. Payout in 8 weeks."),

    _PP(lender="Credit Suite", program_name="Lendavo Affiliate",
        program_type="affiliate", commission_type="flat_fee",
        commission_display="$900+ per commission (tiered)",
        signup_url="https://info.creditsuite.com/affiliate/",
        portal_url="https://cspartner.profitlifter.com/",
        has_api=False, priority=1,
        notes="No cost, no selling, no fulfillment. Profit Lifter platform with automated"
              " website, CRM, marketing. Real-time tracking."),

    _PP(lender="ARF Financial", program_name="Loan Stars",
        program_type="partner", commission_type="percentage",
        commission_display="8% total (4% upfront + 4% over time)",
        signup_url="https://www.arffinancial.com/loanstars/",
        has_api=False, priority=1,
        notes="No annual fees. Stella AI for deal submission (+1% bonus)."
              " Biweekly webinars. Override commissions for recruiting."),

    _PP(lender="StartCap", program_name="Affiliates",
        program_type="affiliate", commission_type="percentage",
        commission_display="2% of funded amount (~$2K on avg $100K deal)",
        signup_url="https://www.startcap.org/affiliates",
        contact_email="Partners@StartCap.org",
        has_api=False, priority=1,
        notes="Quick signup. Partner dashboard for tracking. Funds up to $500K+."),

    _PP(lender="Biz2Credit", program_name="Affiliate Program",
        program_type="affiliate", commission_type="flat_fee",
        commission_display="$200 per funded deal",
        signup_url="https://www.biz2credit.com/partners/affiliate-program",
        has_api=True, priority=1,
        notes="Biz2X embedded finance API available. 203% revenue growth 2021-2024."
              " Low-code/no-code integration options."),

    # Priority 2 — 1-2 week onboarding
    _PP(lender="Greenbox Capital", program_name="ISO Program",
        program_type="iso", commission_type="percentage",
        commission_display="15-19% of funded amount (highest in industry)",
        signup_url="https://www.greenboxcapital.com/iso-application/",
        has_api=False, priority=2,
        notes="'The Box' portal for deal submission. Uber-like experience."
              " Lowest syndication fees. Call 1-855-442-3423."),

    _PP(lender="Credibly", program_name="Agent Program",
        program_type="partner", commission_type="percentage",
        commission_display="3-5% agent commission",
        signup_url="https://www.credibly.com/partner/",
        portal_url="https://portal.credibly.com/dashboard",
        has_api=False, priority=2,
        notes="Dynamic Offers (Aug 2025). Funding Partners or Referral Partners. White label available."),

    _PP(lender="OnDeck", program_name="Partner Program",
        program_type="partner", commission_type="percentage",
        commission_display="Up to $10K per transaction (2% of funded)",
        signup_url="https://www.ondeck.com/partner/referral",
        portal_url="https://partners.ondeck.com/",
        contact_email="partners@ondeck.com",
        has_api=False, priority=2,
        notes="Enterprise, Affiliate, and Accountant tiers. Paid 15 days after month end via check or ACH."),

    _PP(lender="Ramp", program_name="Partnerships",
        program_type="partner", commission_type="recurring",
        commission_display="5% of first-year card spend (recurring)",
        signup_url="https://ramp.com/partnerships",
        has_api=False, priority=2,
        notes="Tiers: Partner > Bronze > Silver > Titanium."
              " Payout after referral spends $1K+. ACH by 3rd week of month."),

    _PP(lender="Brex", program_name="Partner Referrals",
        program_type="partner", commission_type="flat_fee",
        commission_display="$250+ per qualified signup (negotiable)",
        signup_url="https://www.brex.com/partners",
        has_api=True, priority=2,
        notes="Full REST API + Zapier. Submit referrals programmatically. OAuth2 auth. Best-in-class integration."),

    _PP(lender="Mercury", program_name="Partnerships",
        program_type="partner", commission_type="flat_fee",
        commission_display="$250 per qualified signup ($10K deposit req)",
        signup_url="https://mercury.com/partnerships",
        contact_email="partnerships@mercury.com",
        has_api=False, priority=2,
        notes="Custom terms negotiable ($500/referral with $50K deposit). Payout 1st business day of month."),

    # Priority 3 — Longer setup or lower priority
    _PP(lender="Divvy (Bill.com)", program_name="Referral Program",
        program_type="referral", commission_type="flat_fee",
        commission_display="$100 per qualified signup",
        has_api=False, priority=3,
        notes="Referral via existing account. No dedicated partner program page."),

    _PP(lender="Fundbox", program_name="Partner Program",
        program_type="partner", commission_type="flat_fee",
        commission_display="$50 per funded deal",
        signup_url="https://fundbox.com/partners/",
        has_api=True, priority=3,
        notes="Full API for embedded, white-labeled experiences. HasOffers tracking. Partners: Intuit, Stripe, SoFi."),

    _PP(lender="Lendio", program_name="Embedded Marketplace",
        program_type="partner", commission_type="percentage",
        commission_display="Revenue share on funded deals (negotiated)",
        signup_url="https://www.lendio.com/partners",
        has_api=True, priority=3,
        notes="Single JS line deploys marketplace. Offer data via API."
              " IQ instant qualification. Dedicated account manager."),

    _PP(lender="National Funding", program_name="ISO Program",
        program_type="iso", commission_type="percentage",
        commission_display="3% of funded amount",
        signup_url="https://www.nationalfunding.com/partners/",
        has_api=False, priority=3,
        notes="CURRENTLY AT FULL CAPACITY for all ISOs/Brokers. Check back periodically. 24+ years in business."),

    _PP(lender="Kabbage (Amex)", program_name="Business Blueprint",
        program_type="referral", commission_type="flat_fee",
        commission_display="$200 per funded deal (via Amex Business Alliance)",
        signup_url="https://www.americanexpress.com/en-us/business/business-alliance-program/",
        has_api=False, priority=3,
        notes="Kabbage brand retired Jan 2023, now Amex Business Blueprint. Use Amex Business Alliance program."),

    _PP(lender="SBA", program_name="Referral Agent (Form 159)",
        program_type="broker", commission_type="percentage",
        commission_display="2% referral agent fee per deal",
        signup_url="https://www.sba.gov/document/sba-form-159-fee-disclosure-compensation-agreement",
        has_api=False, priority=3,
        notes="Form 159 required per deal. Fee must be 'necessary and reasonable'."
              " Cannot be paid by both borrower AND lender. If >$2500, attach justification."),
]


def seed_partner_programs(db: FundingDB) -> int:
    """Seed partner programs if empty. Returns count inserted."""
    if db.partner_program_count() > 0:
        return 0

    count = 0
    for prog in PARTNER_PROGRAMS:
        db.save_partner_program(prog)
        count += 1

    return count
