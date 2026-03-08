# HIRELY – CV Matching System

HIRELY is a recruitment support system that helps HR teams manage job postings, upload anonymized CVs, and calculate candidate-job matching scores automatically.

## Main Features

- User management with role-based dashboards:
  - HR Manager
  - HR Lead
  - Recruiter
  - DevOps
- Job creation and management
- CV upload and anonymization
- Automatic candidate-to-job linking
- Scoring engine for candidate-job matching
- SQLite-based persistence

## Matching Score Components

The final score is calculated from several components:

- **Age score** – up to 10 points
- **Distance score** – up to 10 points
- **Must requirements score** – up to 40 points
- **Years of experience score** – up to 30 points
- **Nice-to-have requirements score** – up to 10 points

### Distance Logic

- Up to 40 km: full score
- Between 40 km and 100 km: gradual decrease
- Above 100 km: 0 points
- If candidate residence is not found: the score remains `NULL`, and the system gives full default distance points in the final calculation
- Remote jobs: full distance score
- Hybrid jobs: minimum distance score of 5 points

### Experience Logic

- Required years of experience are stored per job
- Candidate experience is extracted from Hebrew CVs
- The experience score is calculated proportionally up to 30 points

## Tech Stack

- **Backend:** Python, Flask
- **Database:** SQLite
- **Frontend:** HTML, CSS, JavaScript
- **Document processing:** PDF/DOCX anonymization and text extraction

## Project Structure

- `auth_server.py` – main Flask server and routes
- `src/utils/db.py` – database utilities and score recomputation
- `src/scoring/experience_score.py` – years-of-experience scoring
- `src/scoring/distance_score.py` – distance scoring
- `src/scoring/israel_cities.json` – cities and coordinates dataset
- `templates/` – dashboard and UI templates

## How to Run

1. Create and activate a virtual environment
2. Install dependencies
3. Run:

```bash
py auth_server.py
4.Open: http://127.0.0.1:5000


Notes

The system currently works with Hebrew CVs

Distance scoring is based on recognized Israeli cities

If a city is not recognized, the system does not penalize the candidate by distance
