// Project plan deck for the thesis (supervisor meeting).
//   NODE_PATH=<dir with pptxgenjs, react-icons, react, react-dom, sharp> node thesis/plan/make_deck.js
// Writes thesis/plan/project-plan.pptx.
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

const HERE = __dirname;
const FIG = path.join(HERE, "..", "report", "figures");
const OUT = path.join(HERE, "project-plan.pptx");
const APPLY_THEME = process.env.APPLY_THEME;   // path to the pptx skill's scripts/apply_theme.js

const THEME = {
  name: "dc-selfheal",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1E293B", lt1: "FFFFFF", dk2: "0F3D3E", lt2: "EEF4F3",
    accent1: "0E7C7B", accent2: "D97706", accent3: "2F9E44", accent4: "C2255C",
    accent5: "2F6DB5", accent6: "7048B6", hlink: "2F6DB5", folHlink: "7048B6",
  },
};
const HEX = THEME.colors;
const LINE = "D3DEDC";            // card outline (not a theme slot)
const MUTED = "5B6B7F";           // secondary text (not a theme slot)
const ON_DARK = "B9D9D6";         // secondary text on the dark title slide

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";      // 13.333 x 7.5 in
pres.title = "Self-healing data hall: thesis project plan";
pres.author = "Mazharul Islam Tusar";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

const FOOT = "Self-healing data hall · Bachelor's thesis plan · Savonia University of Applied Sciences";

pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: HEX.dk2 },
  objects: [],
});
pres.defineSlideMaster({
  title: "CONTENT_LIGHT",
  background: { color: HEX.lt1 },
  margin: [0.5, 0.5, 0.6, 0.5],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.32, w: 12.3, h: 0.7,
        fontSize: 30, bold: true, color: C.text2, align: "left", valign: "middle", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "sub", type: "body", x: 0.5, y: 1.0, w: 12.3, h: 0.42,
        fontSize: 15, italic: true, color: C.accent1, align: "left", valign: "middle", margin: 0 }, text: "" } },
    { text: { text: FOOT, options: { x: 0.5, y: 7.02, w: 10, h: 0.3, fontSize: 10, color: MUTED, margin: 0 } } },
  ],
  slideNumber: { x: 12.3, y: 7.02, w: 0.5, h: 0.3, fontSize: 10, color: MUTED, align: "right" },
});

// ------------------------------------------------------------------ helpers
const iconCache = {};
async function icon(name, color = "#FFFFFF") {
  const key = name + color;
  if (!iconCache[key]) {
    const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(fa[name], { color, size: 256 }));
    const buf = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
    iconCache[key] = "image/png;base64," + buf.toString("base64");
  }
  return iconCache[key];
}

async function iconDot(slide, name, x, y, d, fill) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { color: fill },
    objectName: `icon-bg-${name}` });
  const p = d * 0.22;
  slide.addImage({ data: await icon(name), x: x + p, y: y + p, w: d - 2 * p, h: d - 2 * p, objectName: `icon-${name}` });
}

function card(slide, x, y, w, h, name) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08,
    fill: { color: HEX.lt2 }, line: { color: LINE, width: 1 }, objectName: name });
}

function text(slide, t, o) {
  slide.addText(t, { isTextBox: true, margin: 0, color: C.text1, fontSize: 14, valign: "top", ...o });
}

function bullets(items, size = 13, color = MUTED) {
  return items.map((s, i) => ({ text: s, options: { bullet: { indent: 12 }, fontSize: size, color,
    paraSpaceAfter: 3, breakLine: i < items.length - 1 } }));
}

function arrow(slide, x, y, color = C.accent1) {
  slide.addShape(pres.shapes.RIGHT_ARROW, { x, y, w: 0.32, h: 0.34, fill: { color }, line: { color },
    objectName: "flow-arrow" });
}

function content(section, title, sub) {
  const s = pres.addSlide({ masterName: "CONTENT_LIGHT", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  s.addText(sub, { placeholder: "sub" });
  return s;
}

// ------------------------------------------------------------------ slides
async function build() {
  // 1. Title ---------------------------------------------------------------------------------
  pres.addSection({ title: "Overview" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Overview" });
  text(s, "Self-Healing\nData Hall", { x: 0.6, y: 0.55, w: 6.2, h: 1.9, fontSize: 44, bold: true, color: C.background1, fontFace: THEME.headFontFace });
  text(s, "A serverless AWS IoT framework for automated anomaly detection and remediation in data center infrastructure",
    { x: 0.6, y: 2.5, w: 6.2, h: 0.95, fontSize: 18, color: ON_DARK });
  text(s, "Bachelor's thesis plan  ·  Mazharul Islam Tusar  ·  Savonia University of Applied Sciences",
    { x: 0.6, y: 3.5, w: 6.2, h: 0.35, fontSize: 12, color: ON_DARK });
  s.addImage({ path: path.join(FIG, "aws-dashboard-fault.png"), x: 7.1, y: 0.6, w: 5.75, h: 3.1,
    altText: "Live control-room dashboard showing a cooling failure being fixed", objectName: "hero-dashboard" });
  text(s, "Target demo: live control room while a cooling failure is detected and fixed",
    { x: 7.1, y: 3.78, w: 5.75, h: 0.3, fontSize: 11, italic: true, color: ON_DARK });
  const pillars = [
    ["FaBroadcastTower", "DETECT", HEX.accent5, ["IoT telemetry every 10 s", "Thresholds + machine learning", "Confirmed in 30 s"]],
    ["FaTools", "REMEDIATE", HEX.accent1, ["Playbooks in Step Functions", "Commands via device shadows", "Verified on new telemetry"]],
    ["FaShieldAlt", "GUARD", HEX.accent2, ["Locks and risk tiers", "Human approval if high risk", "Rollback, circuit breaker"]],
  ];
  for (let i = 0; i < 3; i++) {
    const [ic, t, col, items] = pillars[i];
    const x = 0.6 + i * 4.1;
    card(s, x, 4.35, 3.85, 2.1, `pillar-${t}`);
    await iconDot(s, ic, x + 0.25, 4.55, 0.6, col);
    text(s, t, { x: x + 1.0, y: 4.62, w: 2.7, h: 0.45, fontSize: 17, bold: true, valign: "middle" });
    text(s, bullets(items, 13), { x: x + 0.25, y: 5.3, w: 3.45, h: 1.05 });
  }
  text(s, "AWS IoT Core  ·  Lambda  ·  EventBridge  ·  Step Functions  ·  DynamoDB  ·  SNS  ·  AWS CDK  ·  Python",
    { x: 0.6, y: 6.75, w: 12.1, h: 0.35, fontSize: 12, color: ON_DARK });

  // 2. Problem and research questions ---------------------------------------------------------
  s = content("Overview", "Why this thesis", "Facility faults are frequent and costly, and they are still handled by hand");
  const stats = [
    ["415 TWh", "electricity used by data centers in 2024, about 1.5 % of the world total (IEA 2025)", HEX.accent1],
    ["> 40 kW", "drawn by one dense GPU rack: a short loss of cooling can throttle or stop it", HEX.accent2],
    ["57 %", "of operators said their latest significant outage cost over $100,000 (Uptime Institute 2026)", HEX.accent4],
  ];
  stats.forEach(([n, l, col], i) => {
    const y = 1.75 + i * 1.62;
    card(s, 0.5, y, 5.2, 1.42, `stat-${i}`);
    text(s, n, { x: 0.75, y: y + 0.18, w: 2.1, h: 1.05, fontSize: 36, bold: true, color: col, valign: "middle" });
    text(s, l, { x: 2.95, y: y + 0.2, w: 2.55, h: 1.05, fontSize: 12, color: MUTED, valign: "middle" });
  });
  text(s, "RESEARCH QUESTIONS", { x: 6.1, y: 1.75, w: 6.7, h: 0.4, fontSize: 14, bold: true, color: C.accent1 });
  const rqs = [
    ["RQ1", "Design", "How can a serverless AWS architecture turn data center IoT telemetry into safe, automated remediation?"],
    ["RQ2", "Detection", "How does machine-learning detection compare with static thresholds in detection rate, time to detect and false alarms?"],
    ["RQ3", "Impact", "How much does automation shorten recovery compared with alert-only response, and at what latency, scale and cost?"],
  ];
  rqs.forEach(([k, t, q], i) => {
    const y = 2.25 + i * 1.22;
    card(s, 6.1, y, 6.73, 1.07, `rq-${k}`);
    text(s, k, { x: 6.3, y: y + 0.15, w: 0.9, h: 0.75, fontSize: 22, bold: true, color: C.accent1, valign: "middle" });
    text(s, [{ text: t + "  ", options: { bold: true, color: C.text1, fontSize: 14 } },
             { text: q, options: { color: MUTED, fontSize: 13 } }],
      { x: 7.25, y: y + 0.12, w: 5.4, h: 0.85, valign: "middle" });
  });
  text(s, [{ text: "Problem: ", options: { bold: true, color: C.accent2 } },
           { text: "no validated, cloud-native way to go from IoT sensor data to safe, automatic corrective action within seconds.",
             options: { color: C.text1 } }],
    { x: 6.1, y: 6.0, w: 6.73, h: 0.7, fontSize: 14 });

  // 3. Architecture ---------------------------------------------------------------------------
  pres.addSection({ title: "Design" });
  s = content("Design", "System architecture", "Event-driven and serverless: nothing runs until a sensor message arrives");
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.5, y: 1.7, w: 8.0, h: 3.58, rectRadius: 0.08,
    fill: { color: C.background1 }, line: { color: LINE, width: 1 }, objectName: "arch-frame" });
  s.addImage({ path: path.join(FIG, "architecture.png"), x: 0.72, y: 1.92, w: 7.56, h: 3.1,
    altText: "Architecture: gateways, IoT Core, Lambda detector, EventBridge, Step Functions, device shadow", objectName: "arch" });
  text(s, "Gateway → IoT Core → detector Lambda → EventBridge → Step Functions playbook → device shadow → gateway",
    { x: 0.5, y: 5.45, w: 8.0, h: 0.5, fontSize: 13, color: MUTED });
  const services = [
    ["FaWifi", "IoT Core", "MQTT, certificates, rules, shadows", HEX.accent5],
    ["FaBolt", "Lambda", "detector and playbook steps", HEX.accent2],
    ["FaProjectDiagram", "Step Functions", "one generic remediation workflow", HEX.accent1],
    ["FaStream", "EventBridge", "routes anomaly events", HEX.accent6],
    ["FaDatabase", "DynamoDB", "telemetry, incidents, locks", HEX.accent3],
    ["FaBell", "SNS", "alerts and approval emails", HEX.accent4],
  ];
  for (let i = 0; i < services.length; i++) {
    const [ic, n, r, col] = services[i];
    const y = 1.7 + i * 0.75;
    await iconDot(s, ic, 8.85, y + 0.05, 0.5, col);
    text(s, n, { x: 9.5, y, w: 3.3, h: 0.33, fontSize: 14, bold: true });
    text(s, r, { x: 9.5, y: y + 0.32, w: 3.3, h: 0.32, fontSize: 12, color: MUTED });
  }
  text(s, "Infrastructure as code: six AWS CDK stacks, deployed and removed with one command each; developed locally on LocalStack first",
    { x: 0.5, y: 6.05, w: 12.3, h: 0.5, fontSize: 14, color: C.accent1, italic: true });

  // 4. Closed loop and guardrails -------------------------------------------------------------
  s = content("Design", "Closed loop: detect → decide → act → verify", "Every fault type runs through the same playbook workflow with built-in guardrails");
  const steps = [
    ["1  SENSE", HEX.accent5, ["Gateways publish zone telemetry", "MQTT over TLS to IoT Core", "Rule stores and forwards"]],
    ["2  DETECT", HEX.accent6, ["Limits + Isolation Forest", "+ LSTM autoencoder", "3 windows to confirm"]],
    ["3  PLAN", HEX.accent1, ["Playbook by fault type", "Lock assets, precheck", "Assign risk tier"]],
    ["4  APPROVE", HEX.accent2, ["Low risk: automatic", "High risk: one-time link by email or dashboard"]],
    ["5  ACT + VERIFY", HEX.accent3, ["Command via device shadow", "Check the next telemetry", "Close, roll back or escalate"]],
  ];
  const sw = 2.22, sg = 0.3;
  steps.forEach(([t, col, items], i) => {
    const x = 0.5 + i * (sw + sg);
    card(s, x, 1.75, sw, 2.2, `step-${i}`);
    s.addShape(pres.shapes.OVAL, { x: x + 0.2, y: 1.95, w: 0.22, h: 0.22, fill: { color: col }, line: { color: col }, objectName: `step-dot-${i}` });
    text(s, t, { x: x + 0.52, y: 1.88, w: sw - 0.6, h: 0.38, fontSize: 15, bold: true, valign: "middle" });
    text(s, bullets(items, 12), { x: x + 0.2, y: 2.45, w: sw - 0.35, h: 1.75 });
    if (i < steps.length - 1) arrow(s, x + sw - 0.01, 2.68);
  });
  text(s, "GUARDRAILS", { x: 0.5, y: 4.3, w: 4, h: 0.4, fontSize: 14, bold: true, color: C.accent2 });
  const guards = [
    ["FaLock", "Asset locks", "no two playbooks on one asset"],
    ["FaUserCheck", "Human approval", "for high-risk actions"],
    ["FaRedo", "Recheck", "on fresh data before acting"],
    ["FaUndo", "Rollback", "if verification fails"],
    ["FaPowerOff", "Circuit breaker", "stops after two failures"],
    ["FaTachometerAlt", "Rate limit", "max actions per hour"],
  ];
  for (let i = 0; i < guards.length; i++) {
    const [ic, n, d] = guards[i];
    const x = 0.5 + i * 2.06;
    card(s, x, 4.75, 1.9, 1.75, `guard-${i}`);
    await iconDot(s, ic, x + 0.15, 4.92, 0.5, HEX.accent2);
    text(s, n, { x: x + 0.15, y: 5.55, w: 1.65, h: 0.32, fontSize: 13, bold: true });
    text(s, d, { x: x + 0.15, y: 5.88, w: 1.65, h: 0.55, fontSize: 12, color: MUTED });
  }

  // 5. Detection and modes --------------------------------------------------------------------
  pres.addSection({ title: "Method" });
  s = content("Method", "Detection and operating modes", "Three ways of responding are compared on eight injected fault types");
  const modes = [
    ["M1", "Alert only", "Static limits raise an alert; a simulated operator responds after 5–30 minutes", HEX.accent4, "Today's practice"],
    ["M2", "Threshold automation", "Static limits start the playbooks automatically", HEX.accent2, "Effect of automation"],
    ["M3", "ML automation", "Hybrid ML detector starts the playbooks automatically", HEX.accent3, "Effect of ML detection"],
  ];
  modes.forEach(([k, n, d, col, tag], i) => {
    const x = 0.5 + i * 2.62;
    card(s, x, 1.75, 2.42, 2.95, `mode-${k}`);
    text(s, k, { x: x + 0.2, y: 1.9, w: 1.2, h: 0.6, fontSize: 28, bold: true, color: col });
    text(s, n, { x: x + 0.2, y: 2.55, w: 2.05, h: 0.4, fontSize: 15, bold: true });
    text(s, d, { x: x + 0.2, y: 3.0, w: 2.05, h: 1.05, fontSize: 12, color: MUTED });
    text(s, tag, { x: x + 0.2, y: 4.2, w: 2.05, h: 0.35, fontSize: 11, italic: true, color: col });
  });
  text(s, "DETECTORS", { x: 0.5, y: 4.95, w: 4, h: 0.4, fontSize: 14, bold: true, color: C.accent1 });
  const dets = [["D0", "Static limits"], ["D1", "Isolation Forest"], ["D2", "LSTM autoencoder"], ["D1h / D2h", "+ diagnosis rules"]];
  dets.forEach(([k, n], i) => {
    const x = 0.5 + i * 1.98;
    card(s, x, 5.38, 1.84, 1.15, `det-${i}`);
    text(s, k, { x: x + 0.15, y: 5.48, w: 1.6, h: 0.4, fontSize: 15, bold: true, color: C.accent1 });
    text(s, n, { x: x + 0.15, y: 5.88, w: 1.6, h: 0.55, fontSize: 12, color: MUTED });
  });
  text(s, "8 FAULT TYPES", { x: 8.55, y: 1.75, w: 4.3, h: 0.4, fontSize: 14, bold: true, color: C.accent2 });
  const faults = [
    ["FaFan", "CRAH fan failure", "cooling"], ["FaCog", "Pump degradation", "cooling"],
    ["FaTint", "Chilled-water drift", "cooling"], ["FaFire", "Rack hotspot", "cooling"],
    ["FaPlug", "PDU overload", "power"], ["FaCarBattery", "UPS battery overheat", "power"],
    ["FaWaveSquare", "Sensor drift", "sensor"], ["FaPause", "Sensor stuck", "sensor"],
  ];
  for (let i = 0; i < faults.length; i++) {
    const [ic, n, kind] = faults[i];
    const col = kind === "power" ? HEX.accent2 : kind === "sensor" ? HEX.accent6 : HEX.accent5;
    const x = 8.55 + (i % 2) * 2.18, y = 2.2 + Math.floor(i / 2) * 0.75;
    card(s, x, y, 2.08, 0.62, `fault-${i}`);
    await iconDot(s, ic, x + 0.1, y + 0.1, 0.42, col);
    text(s, n, { x: x + 0.6, y: y + 0.05, w: 1.45, h: 0.52, fontSize: 11, bold: true, valign: "middle" });
  }
  text(s, [{ text: "Data: ", options: { bold: true, color: C.accent1 } },
           { text: "simulated data hall with known ground truth; public SKAB pump data for validation on real equipment",
             options: { color: MUTED } }],
    { x: 8.55, y: 5.38, w: 4.28, h: 1.15, fontSize: 13 });

  // 6. Evaluation plan ------------------------------------------------------------------------
  s = content("Method", "Evaluation plan", "Design Science Research: eight testable hypotheses, five experiments");
  const hyps = [
    ["H1", "Faster recovery", "M2 faster than M1"], ["H2", "Better detection", "M3 finds all 8 faults"],
    ["H3", "No false actions", "0 automated false actions"], ["H4", "Real-data validity", "SKAB F1 ≥ limits"],
    ["H5", "Safe automation", "0 wrong actions"], ["H6", "Within seconds", "≤ 5 s to first command"],
    ["H7", "Scalable", "p95 ≤ 1 s at 2,000 gateways"], ["H8", "Affordable", "≤ $1 per rack per month"],
  ];
  hyps.forEach(([k, n, c], i) => {
    const x = 0.5 + (i % 2) * 3.0, y = 1.75 + Math.floor(i / 2) * 1.2;
    card(s, x, y, 2.85, 1.05, `hyp-${k}`);
    text(s, k, { x: x + 0.15, y: y + 0.15, w: 0.7, h: 0.75, fontSize: 22, bold: true, color: C.accent1, valign: "middle" });
    text(s, n, { x: x + 0.85, y: y + 0.14, w: 1.95, h: 0.38, fontSize: 13, bold: true });
    text(s, c, { x: x + 0.85, y: y + 0.52, w: 1.95, h: 0.42, fontSize: 11, color: MUTED });
  });
  const hdr = (t) => ({ text: t, options: { bold: true, color: C.background1, fill: { color: C.accent1 }, fontSize: 12 } });
  const cell = (t, o = {}) => ({ text: t, options: { color: C.text1, fill: { color: C.background1 }, fontSize: 12, ...o } });
  const rows = [
    [hdr("Exp."), hdr("Question"), hdr("Design"), hdr("Runs")],
    [cell("E1", { bold: true }), cell("Fault response"), cell("8 faults × 3 modes × 20 paired seeds"), cell("480")],
    [cell("E2", { bold: true }), cell("Scalability"), cell("Load test on AWS: 50, 500, 2,000 gateways"), cell("3 levels")],
    [cell("E3", { bold: true }), cell("Cost"), cell("Cost model with measured usage; AWS bill"), cell("–")],
    [cell("E4", { bold: true }), cell("Robustness"), cell("Load surges, faulty sensor, 5–20 % message loss"), cell("600")],
    [cell("E5", { bold: true }), cell("Severity"), cell("8 faults × 3 severities × 3 modes × 10 seeds"), cell("720")],
  ];
  s.addTable(rows, { x: 6.75, y: 1.75, w: 6.08, colW: [0.7, 1.35, 3.18, 0.85], rowH: 0.55,
    border: { type: "solid", pt: 1, color: LINE }, valign: "middle", margin: 0.06, objectName: "experiments" });
  text(s, [{ text: "Statistics: ", options: { bold: true, color: C.accent1 } },
           { text: "paired runs, Mann–Whitney U with Holm correction, bootstrap 95 % confidence intervals",
             options: { color: MUTED } }],
    { x: 6.75, y: 5.35, w: 6.08, h: 0.7, fontSize: 13 });
  text(s, [{ text: "Fast and cheap: ", options: { bold: true, color: C.accent2 } },
           { text: "hundreds of runs in an offline closed loop; AWS only for latency, scale and cost",
             options: { color: MUTED } }],
    { x: 6.75, y: 6.05, w: 6.08, h: 0.7, fontSize: 13 });

  // 7. Roadmap --------------------------------------------------------------------------------
  pres.addSection({ title: "Plan" });
  s = content("Plan", "Roadmap and deliverables", "Built step by step: locally first, then on AWS");
  const phases = [
    ["1", "Foundation", "Repository, CDK skeleton, LocalStack, simulator and fault injection", "1–3", HEX.accent5],
    ["2", "Telemetry pipeline", "Gateways, MQTT, topic rule, DynamoDB", "3–4", HEX.accent5],
    ["3", "Detection", "Limits, Isolation Forest, LSTM autoencoder, rules; SKAB validation", "4–7", HEX.accent6],
    ["4", "Remediation", "Step Functions playbooks, device shadows, notifications", "7–9", HEX.accent1],
    ["5", "Guardrails", "Locks, approval, recheck, rollback, circuit breaker, rate limit", "9–10", HEX.accent2],
    ["6", "Experiments", "E1, E4, E5 in the offline closed loop; statistics", "10–13", HEX.accent3],
    ["7", "AWS + dashboard", "Live check, load test, cost; live control-room dashboard", "13–15", HEX.accent4],
    ["8", "Thesis report", "Writing, feedback, language check, Turnitin, presentation", "15–18", HEX.accent2],
  ];
  phases.forEach(([k, n, d, wk, col], i) => {
    const y = 1.62 + i * 0.56;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.5, y, w: 1.1, h: 0.46, rectRadius: 0.06,
      fill: { color: col }, line: { color: col }, objectName: `phase-${k}` });
    text(s, "STEP " + k, { x: 0.5, y, w: 1.1, h: 0.46, fontSize: 12, bold: true, color: C.background1, align: "center", valign: "middle" });
    card(s, 1.75, y, 7.6, 0.46, `phase-row-${k}`);
    text(s, n, { x: 1.9, y, w: 2.0, h: 0.46, fontSize: 13, bold: true, valign: "middle" });
    text(s, d, { x: 3.9, y, w: 4.6, h: 0.46, fontSize: 11, color: MUTED, valign: "middle" });
    text(s, "wk " + wk, { x: 8.45, y, w: 0.82, h: 0.46, fontSize: 11, color: C.accent1, align: "right", valign: "middle" });
  });
  card(s, 9.65, 1.62, 3.18, 2.6, "final-demo");
  await iconDot(s, "FaFlagCheckered", 9.85, 1.8, 0.5, HEX.accent3);
  text(s, "FINAL DEMO", { x: 10.5, y: 1.85, w: 2.2, h: 0.4, fontSize: 15, bold: true, color: C.accent3, valign: "middle" });
  text(s, "A CRAH unit fails in the simulated hall on AWS. The detector finds it, the playbook starts the standby unit and verifies the recovery, and a high-risk UPS fault waits for approval, all live on the dashboard.",
    { x: 9.85, y: 2.45, w: 2.85, h: 1.85, fontSize: 12, color: MUTED });
  card(s, 9.65, 4.42, 3.18, 2.12, "deliverables");
  text(s, "DELIVERABLES", { x: 9.85, y: 4.57, w: 2.8, h: 0.35, fontSize: 14, bold: true, color: C.accent1 });
  text(s, bullets(["Open-source code and tests", "Six CDK stacks on AWS", "Reproducible experiment data", "Live dashboard", "Thesis report"], 12),
    { x: 9.85, y: 4.98, w: 2.85, h: 1.5 });

  await pres.writeFile({ fileName: OUT });
  if (APPLY_THEME) {
    const { applyTheme } = require(APPLY_THEME);
    await applyTheme(OUT, THEME);
  }
  console.log("written", OUT);
}

build().catch((e) => { console.error(e); process.exit(1); });
