# Driver Drowsiness Dashboard (Module 5)

This is a minimal React (Vite) dashboard scaffold for Module 5 — Live Monitoring, Trips list, and Trip Detail pages. It uses placeholder data and a laptop webcam feed for the Live Monitoring page.

Quick start:

```bash
npm install
npm run dev
```

Pages:
- Live Monitoring: `/live` (default) — webcam, speed, risk, small map.
- Trips: `/trips` — table of trips, View Details.
- Trip Detail: `/trips/:id` — map replay placeholder, stats, AI analysis, alert history.

Files of interest:
- [package.json](package.json)
- [src/App.jsx](src/App.jsx)
- [src/pages/LiveMonitoring.jsx](src/pages/LiveMonitoring.jsx)
