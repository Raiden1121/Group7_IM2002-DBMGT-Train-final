# TransitFlow Policy Extensions Summary & Score Assessment

## 📝 Part 1: Summary of JSON Policy Changes

We successfully expanded all four Vector Database (RAG) knowledge files to include complex, realistic transit policies.

### 1. `ticket_types.json` (Ticket Policies)
*   **Tiered Group Fares**: Replaced a flat 20% discount with a realistic tier system (TRA model):
    *   10–19 passengers: No discount, but guaranteed seating together.
    *   20–49 passengers: 20% off.
    *   50+ passengers: 35% off.
*   **Requirements**: Added strict booking rules (max 35 days in advance) and conditions (must share same origin/destination/service).

### 2. `travel_policies.json` (General Travel Rules)
*   **Categorized Lost Property**: 
    *   High-value items/IDs: Transferred immediately to Central Station (NR01) secure storage.
    *   Ordinary items: Kept at local station for 3 days, then transferred.
    *   Dangerous goods/Perishables: Safely disposed of or neutralized.
*   **Claim Verification**: Implemented strict ID, proof of travel, and detailed description requirements.
*   **Accessibility (Moved to Dual-Network Level)**:
    *   **Carer Discount**: 50% off for companions of passengers with valid disability IDs.
    *   **Facilities & Service Animals**: Tactile paving at all stations; guide dogs travel for free across the network without carriers.

### 3. `refund_policy.json` (Refund Rules)
*   **RF006 (Force Majeure)**: 100% refund with zero admin fee for severe weather/natural disasters.
*   **RF007 (Missed Connection Guarantee)**: Free rebooking or full refund if a passenger misses a National Rail train due to a delayed Metro/Rail connection.
*   **RF008 (Strikes & Disruptions)**: 100% reimbursement for alternative transport (taxis/flights), with an anti-abuse clause explicitly stating tickets must have been bought *before* the strike announcement.

### 4. `booking_rules.json` (Booking Fares)
*   **Synchronized Group Fares**: Refactored the old logic to point directly to `ticket_types.json` breakpoints, preventing LLM confusion.
*   **Senior Fares**: 50% discount for passengers aged 65 and over.
*   **Student Fares**: 20% discount on standard class tickets with a valid ISIC or domestic student ID.
*   **Promotional Fares**: 
    *   *Early Bird*: 30% discount if booked 28 days in advance (non-refundable).
    *   *Off-Peak*: 15% discount for weekday travel between 10:00 - 15:00.

---

## 🏆 Part 2: Task 6 Extension Score Assessment

Based on the `score/STUDENT_GUIDE_CODE.md` and `score/STUDENT_GUIDE_LIVE.md` grading rubrics, here is your progress towards the **+15 Task 6 Bonus**:

### ✅ What You Have Accomplished (Full Marks)
*   **Touches database code (2/2)**: We extensively expanded the seed data for the pgvector database.
*   **Quality of database implementation (5/5)**: The JSON structure is highly nested, logical, and perfect for LLM embedding retrieval.
*   **Code comments (3/3)**: We cleverly used `_developer_note` as inline comments within the JSON files to explain the *why* behind our structural choices.

### ⚠️ What You Are Currently Missing (Action Required)
To guarantee the +15 bonus, the rubrics clearly state that **all four of the following must be present**. You are missing three administrative requirements:

1.  ❌ **`TASK6.md` Tracker File**: The rubric states: *"A `TASK6.md` file at the repo root lists every file modified or added"*. You need to create this file and list our 4 JSON files.
2.  ❌ **File-level Extension Markers**: The rubric states: *"Each modified file must also have a `# TASK 6 EXTENSION:` comment near the top."* Since JSON doesn't support `#` comments, we should add a key like `"_task6_extension": "TASK 6 EXTENSION"` to the top of all 4 files so the TAs can identify them.
3.  ❌ **Design Document - Section 7**: You must write a Section 7 in your Markdown Design Document detailing the motivation for these RAG policy changes, and showing examples of how the LLM uses them.
4.  🔄 **Live Demonstrability**: To get the live bonus, we must actually run `python skeleton/seed_vectors.py` so the data is loaded, and then you must test it in the chat UI and take screenshots for your report.
