"""Verify _replace_company_bullets now preserves backslashes."""
import sys
sys.path.insert(0, '.')
from agents.resume_tailor_agent import ResumeTailorAgent

agent = ResumeTailorAgent.__new__(ResumeTailorAgent)

fixed_bullets = (
    "\\resumeItemListStart\n"
    "  \\resumeItem{Built \\textbf{ML pipeline} for production.}\n"
    "  \\resumeItem{Deployed \\textbf{models} at scale.}\n"
    "\\resumeItemListEnd"
)

with open("data/base_resume.tex", "r", encoding="utf-8") as f:
    base_tex = f.read()

result = agent._replace_company_bullets(base_tex, "Mesons", fixed_bullets)

# Find the Mesons experience block and check bytes
mesons_idx = result.find("Mesons Technologies")
chunk = result[mesons_idx:mesons_idx+500]

# Find first resumeItemListStart after Mesons subheading
ri_idx = chunk.find("resumeItemListStart")
byte_before = chunk[ri_idx - 1]
print(f"Byte before 'resumeItemListStart': 0x{ord(byte_before):02x}")

if ord(byte_before) == 0x5c:  # backslash
    print("PASS: proper backslash preserved")
elif ord(byte_before) == 0x0d:  # CR
    print("FAIL: CR control character (regex replacement corruption)")
else:
    print(f"UNEXPECTED: {byte_before!r}")

# Also check textbf
tb_idx = chunk.find("textbf")
if tb_idx > 0:
    byte_before_tb = chunk[tb_idx - 1]
    print(f"Byte before 'textbf': 0x{ord(byte_before_tb):02x}")
    if ord(byte_before_tb) == 0x5c:
        print("PASS: \\textbf backslash preserved")
    elif ord(byte_before_tb) == 0x09:
        print("FAIL: TAB control character")
