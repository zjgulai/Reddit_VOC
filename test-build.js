const fs = require('fs');

console.log("Checking SnapshotReports imports...");
const snapshotContent = fs.readFileSync('ref/UI/momcozy-reddit-workbench/src/pages/SnapshotReports.tsx', 'utf8');
if (snapshotContent.includes("DailyLiveView")) {
  console.log("DailyLiveView is imported in SnapshotReports.tsx");
} else {
  console.error("ERROR: DailyLiveView is NOT imported in SnapshotReports.tsx");
}

console.log("Checking tabConfig...");
if (snapshotContent.includes("live: { label: '今日动态'")) {
  console.log("tabConfig includes 'live'");
} else {
  console.error("ERROR: tabConfig does NOT include 'live'");
}

console.log("Checking fetch endpoint...");
const liveViewContent = fs.readFileSync('ref/UI/momcozy-reddit-workbench/src/components/reports/DailyLiveView.tsx', 'utf8');
if (liveViewContent.includes("fetch('/api/daily-report/latest')")) {
  console.log("fetch points to /api/daily-report/latest");
} else {
  console.error("ERROR: fetch does NOT point to /api/daily-report/latest");
}
