import anthropic
import os
import datetime
import csv
from fpdf import FPDF

# --- DYNAMIC INPUTS ---
CURRENT_CHAPTER_TITLE = "The Lineage of Terah"
CHAPTER_NUMBER = "5"
PROJECT_NAME = "Canon Chronicles"
EMPLOYEE_NAME = "John Doe"
AI_VENDOR = "Claude"  # Options: "Claude" or "NovelCraft"

# --- BUDGET CONFIGURATION ---
TOTAL_PROJECT_BUDGET = 50.00  
TOTAL_BOOK_CHAPTERS = 40 

# --- CONFIGURATION ---
HISTORY_FILE = "usage_history.csv"

# --- 0. PRE-FLIGHT BUDGET CHECK ---
def get_current_spend():
    total_spent = 0.0
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_spent += float(row.get('Cost', 0))
    return total_spent

current_spent = get_current_spend()
remaining_balance = TOTAL_PROJECT_BUDGET - current_spent

# Hard Stop if budget is empty
if remaining_balance <= 0:
    print(f"\n!!! ERROR: BUDGET EXHAUSTED (${current_spent:.2f} / ${TOTAL_PROJECT_BUDGET:.2f}) !!!")
    print("Action Required: Manager must allocate more funds to continue.")
    exit()
elif remaining_balance < 5.00:
    print(f"\n--- WARNING: LOW BUDGET ({remaining_balance:.2f} remaining) ---")

# --- INITIALIZE CLIENT ---
# IMPORTANT: Replace with your real API key
client = anthropic.Anthropic(api_key="your_api_key_here")

# Official Brand Colors (RGB)
VENDOR_COLORS = {
    "Claude": (193, 95, 60),      # Anthropic Orange
    "NovelCraft": (11, 12, 16)    # Deep Navy
}

# --- DATA LOADING ---
def load_file(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f: return f.read()
    return "No data found."

# --- 1. CALL THE AI ENGINE ---
response = client.beta.prompt_caching.messages.create(
    model="claude-3-7-sonnet-latest", 
    max_tokens=4000, 
    extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
    thinking={"type": "enabled", "budget_tokens": 1024},
    system=[
      {"type": "text", "text": "Master novelist. Verify canon.", "cache_control": {"type": "ephemeral"}},
      {"type": "text", "text": f"WORLD BIBLE:\n{load_file('world_bible.txt')}", "cache_control": {"type": "ephemeral"}},
      {"type": "text", "text": f"CHARACTER BIBLE:\n{load_file('character_bible.txt')}", "cache_control": {"type": "ephemeral"}},
      {"type": "text", "text": f"BOOK CANON:\n{load_file('book_pack.txt')}", "cache_control": {"type": "ephemeral"}}
    ],
    messages=[{"role": "user", "content": f"Write Chapter {CHAPTER_NUMBER}: {CURRENT_CHAPTER_TITLE}."}]
)

# --- 2. OUTPUT PROSE TO TERMINAL ---
print(f"Engine Model Used: {response.model}\n")
for block in response.content:
    if block.type == "thinking":
        print(f"--- CLAUDE'S INTERNAL CANON CHECK ---\n{block.thinking}\n")
    elif block.type == "text":
        print(f"--- FINAL PROSE ---\n{block.text}\n")

# --- 3. DATA LOGGING ---
def log_usage(usage_obj, cost, savings):
    file_exists = os.path.isfile(HISTORY_FILE)
    with open(HISTORY_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Date", "Employee", "Chapter", "Title", "Cost", "Savings", "Vendor"])
        writer.writerow([datetime.date.today().isoformat(), EMPLOYEE_NAME, CHAPTER_NUMBER, CURRENT_CHAPTER_TITLE, cost, savings, AI_VENDOR])

# --- 4. PDF REPORT GENERATOR ---
class ExecutivePDF(FPDF):
    def footer(self):
        self.set_y(-25)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(100, 100, 100)
        footer_text = ("Definition of a Token: A token is the basic unit of text processing. 'Prompt Caching' allows us to store large datasets (Bibles) in the AI's memory, reducing costs by 90% per reuse.")
        self.multi_cell(0, 4, footer_text, align='C')

def generate_executive_pdf(usage_obj, current_cost, current_savings):
    log_usage(usage_obj, current_cost, current_savings)
    today_str = datetime.date.today().isoformat()
    now_str = datetime.datetime.now().strftime("%H%M%S")
    daily = {'cost': 0, 'savings': 0, 'requests': 0}
    total = {'cost': 0, 'savings': 0, 'requests': 0}
    
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                c, s = float(row['Cost']), float(row['Savings'])
                total['cost'] += c; total['savings'] += s; total['requests'] += 1
                if row['Date'] == today_str:
                    daily['cost'] += c; daily['savings'] += s; daily['requests'] += 1

    pdf = ExecutivePDF()
    pdf.add_page()
    
    budget_used_pc = (total['cost'] / TOTAL_PROJECT_BUDGET) * 100
    if budget_used_pc < 70: health_color = (46, 139, 87); status = "HEALTHY"
    elif budget_used_pc < 90: health_color = (218, 165, 32); status = "WARNING"
    else: health_color = (178, 34, 34); status = "CRITICAL"

    pdf.set_fill_color(*health_color)
    pdf.rect(160, 10, 40, 10, 'F')
    pdf.set_xy(160, 10)
    pdf.set_font("Helvetica", "B", 8); pdf.set_text_color(255, 255, 255)
    pdf.cell(40, 10, f"STATUS: {status}", 0, 0, 'C')

    pdf.set_xy(10, 10); pdf.set_text_color(40, 40, 40); pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 15, f"Operations Report: {PROJECT_NAME}", ln=True, align='L')
    pdf.set_font("Helvetica", "", 10); pdf.cell(0, 5, f"Lead Employee: {EMPLOYEE_NAME} | Date: {today_str}", ln=True, align='L')
    
    pdf.ln(5); pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, "1. Key Performance Metrics", ln=True)
    pdf.set_fill_color(40, 40, 40); pdf.set_text_color(255, 255, 255); pdf.set_font("Helvetica", "B", 10)
    pdf.cell(60, 10, " Category", 1, 0, 'L', True); pdf.cell(70, 10, " Metric", 1, 0, 'L', True); pdf.cell(60, 10, " Value", 1, 1, 'L', True)
    
    pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "", 10)
    rows = [
        ["Budget Tracking", "Total Project Budget", f"${TOTAL_PROJECT_BUDGET:.2f}"],
        ["Budget Tracking", "Budget Consumed (%)", f"{budget_used_pc:.1f}%"],
        ["Daily Activity", "Daily Cost / Savings", f"${daily['cost']:.4f} / ${daily['savings']:.4f}"],
        ["Project Total", "Total Net Investment", f"${total['cost']:.2f}"]
    ]
    for r in rows:
        pdf.cell(60, 10, r[0], 1); pdf.cell(70, 10, r[1], 1); pdf.cell(60, 10, r[2], 1, 1)

    pdf.ln(10); pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, f"2. Daily Cost Efficiency ({AI_VENDOR} Architecture)", ln=True)
    
    chart_y = pdf.get_y() + 5
    max_val = max(daily['cost'], daily['savings'], 0.5)
    scale = 120 / max_val
    
    pdf.set_fill_color(*VENDOR_COLORS.get(AI_VENDOR, (100, 100, 100)))
    pdf.rect(70, chart_y, daily['cost'] * scale, 8, 'F')
    pdf.set_xy(10, chart_y); pdf.set_font("Helvetica", "", 9); pdf.cell(55, 8, f"{AI_VENDOR} Cost:", 0, 1)
    
    pdf.set_fill_color(46, 139, 87)
    pdf.rect(70, chart_y + 12, daily['savings'] * scale, 8, 'F')
    pdf.set_xy(10, chart_y + 12); pdf.cell(55, 8, "Caching Savings:", 0, 1)

    pdf.ln(15); pdf.set_font("Helvetica", "B", 12); pdf.cell(0, 10, "3. Completion Forecast", ln=True)
    avg_cost = total['cost'] / total['requests'] if total['requests'] > 0 else 0
    left = max(0, TOTAL_BOOK_CHAPTERS - total['requests'])
    est_total_project = total['cost'] + (left * avg_cost)
    
    pdf.set_font("Helvetica", "", 10)
    forecast_txt = f"Projected cost for remaining {left} chapters: ${left * avg_cost:.2f}.\n"
    forecast_txt += f"Total estimated project cost: ${est_total_project:.2f} (Budget: ${TOTAL_PROJECT_BUDGET:.2f})"
    
    if est_total_project > TOTAL_PROJECT_BUDGET:
        pdf.set_text_color(178, 34, 34)
        forecast_txt += "\nALERT: Current budget is INSUFFICIENT for project completion."
    
    pdf.multi_cell(0, 7, forecast_txt)
    pdf.output(f"ExecReport_Ch{CHAPTER_NUMBER}_{now_str}.pdf")
    print(f"\n[REPORT CREATED] PDF saved with Budget Health Badge.")

# --- 5. CALCULATION & USER TERMINAL OUTPUT ---
def print_cost_report(usage_obj):
    # Retrieve caching data safely
    c_read = getattr(usage_obj, 'cache_read_input_tokens', 0)
    c_write = getattr(usage_obj, 'cache_creation_input_tokens', 0)
    
    # Calculate costs based on Claude 3.7 Sonnet pricing
    cost = ((c_write/1e6)*3.75) + ((c_read/1e6)*0.30) + ((usage_obj.input_tokens/1e6)*3.00) + ((usage_obj.output_tokens/1e6)*15.00)
    savings = (c_read / 1e6) * (2.70) # Savings vs non-cached input
    
    new_balance = remaining_balance - cost
    
    print(f"--- COST ANALYSIS ---")
    print(f"Actual Request Cost: ${cost:.4f}")
    print(f"Caching Savings: ${savings:.4f}")
    print(f"Remaining Project Balance: ${new_balance:.2f}")
    
    return cost, savings

# --- 6. MAIN EXECUTION ---
# This invokes the reporting logic
current_cost, current_savings = print_cost_report(response.usage)
generate_executive_pdf(response.usage, current_cost, current_savings)
