const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, AlignmentType, LevelFormat,
} = require("docx");

const INK = "1F1F1F", MUTED = "6B6B6B", ACCENT = "C2410C", LINE = "D9D9D9";
const FONT = "Calibri";

// [[text]] = a placeholder the author fills in (yellow highlight); **text** = bold
function runs(text, opts = {}) {
  const out = [];
  const re = /(\[\[[^\]]+\]\]|\*\*[^*]+\*\*)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...opts }));
    const t = m[0];
    if (t.startsWith("[[")) out.push(new TextRun({ text: "[" + t.slice(2, -2) + "]", highlight: "yellow", ...opts }));
    else out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...opts }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...opts }));
  return out;
}
const p = (text, extra = {}) => new Paragraph({ children: runs(text), spacing: { after: 140, line: 300 }, ...extra });
const bullet = (text) => new Paragraph({ children: runs(text), numbering: { reference: "bullets", level: 0 }, spacing: { after: 60, line: 290 } });
const num = (text) => new Paragraph({ children: runs(text), numbering: { reference: "rqs", level: 0 }, spacing: { after: 80, line: 290 } });
const prompt = (text) => new Paragraph({ children: [new TextRun({ text, italics: true, color: MUTED, size: 19 })], spacing: { after: 160 } });
const field = (label, required) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  children: [new TextRun({ text: label }), ...(required ? [new TextRun({ text: "  *required", color: ACCENT, size: 18, bold: false })] : [])],
  spacing: { before: 360, after: 80 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: LINE, space: 4 } },
});

const cellBorder = { style: BorderStyle.SINGLE, size: 4, color: LINE };
const borders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };
function infoRow(label, value) {
  return new TableRow({ children: [
    new TableCell({ width: { size: 2800, type: WidthType.DXA }, borders,
      shading: { fill: "F4F4F2", type: ShadingType.CLEAR, color: "auto" },
      margins: { top: 90, bottom: 90, left: 120, right: 120 },
      children: [new Paragraph({ children: [new TextRun({ text: label, bold: true, size: 20 })] })] }),
    new TableCell({ width: { size: 6226, type: WidthType.DXA }, borders,
      margins: { top: 90, bottom: 90, left: 120, right: 120 },
      children: [new Paragraph({ children: runs(value, { size: 20 }) })] }),
  ] });
}
const infoTable = (rows) => new Table({ width: { size: 9026, type: WidthType.DXA }, columnWidths: [2800, 6226],
  rows: rows.map(([a, b]) => infoRow(a, b)) });

const children = [
  new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun("Thesis topic proposal")], spacing: { after: 80 } }),
  new Paragraph({ children: [new TextRun({ text: "Answers for the “Create a topic proposal” form, one section per field. Copy each block into the matching box. Highlighted bits are yours to fill in.", color: MUTED })], spacing: { after: 240 } }),

  field("Thesis information"),
  infoTable([
    ["Thesis title in English", "A Serverless AWS IoT Framework for Automated Anomaly Detection and Remediation in Data Center Infrastructure"],
    ["Thesis title in Finnish", "Palvelimeton AWS IoT -kehys datakeskusinfrastruktuurin poikkeamien automaattiseen havaitsemiseen ja korjaamiseen [[have a Finnish speaker check this]]"],
    ["Specialisation", "[[your programme’s specialisation option]]"],
    ["Planned start and end date", "[[1 Sep 2026]] – [[31 Mar 2027]]"],
    ["Thesis type", "Research-oriented development work"],
    ["Advising time preference", "[[Day / Evening / Any]]"],
  ]),

  field("Choice of topic", true),
  prompt("Define a potential commissioner to the thesis and indicate the source of the topic. Why did you become interested in the topic and, if applicable, how is it related to your future or current work? What is the purpose and aim of your thesis? What research questions do you want to address and find solutions to?"),
  p("There’s no commissioner yet; this one is self-initiated. If I had to picture who’d want it, it’s a data center operator or a colocation provider. Basically anyone who’s been woken up at 3 a.m. by a cooling alarm and had to go in and sort it out."),
  p("The idea came from reading outage reports. Uptime Institute keeps finding the same thing year after year: power and cooling failures are still behind most of the expensive outages. And the response is still mostly manual. An alarm goes off. Someone looks at it. Then, a while later, someone acts. That gap between “something’s wrong” and “it’s fixed” is where the damage happens, and with today’s dense AI racks it doesn’t take long."),
  p("There’s a more practical reason too. AWS retired IoT Analytics, IoT Events and Lookout for Equipment in 2025, so if you wanted to build this kind of automation on AWS today, there’s no current design to copy. That felt like a gap worth filling."),
  p("[[A sentence or two in your own words: why this topic grabbed you, and how it connects to your current or future work.]]"),
  p("The aim is easy to say and harder to do. I want to build a serverless system on AWS that spots faults in cooling and power equipment from sensor data and fixes them on its own… safely. Risky actions wait for a person to approve them, and every action is checked afterwards and undone if it didn’t help."),
  p("The research questions:", { spacing: { after: 80 } }),
  num("How can a serverless AWS architecture turn data center IoT telemetry into safe, automatic fixes?"),
  num("Does machine-learning detection actually beat plain fixed thresholds: in what it catches, how fast it catches it, and how many false alarms it raises?"),
  num("How much faster does automated repair get things back to normal than alert-and-wait, and what does that cost in latency, scale and money?"),

  field("Thesis implementation"),
  prompt("Describe in brief how the thesis project is to be implemented. What steps and concrete measures will be taken? What is the type of thesis (research-oriented work, development work, production etc.)? What methods, working procedures etc. will be adopted? Will you collect research material and, if applicable, from whom using which methods? What is the preliminary schedule of your thesis project?"),
  p("It’s development work with a research backbone. I’m following Design Science Research, which sounds grand but really means: build the thing, then test it honestly against the problem it’s supposed to solve."),
  p("First comes a literature review, so I know what’s already been tried. Then I build a simulated data hall: 20 racks, cooling units, pumps, UPS and power distribution, all sending sensor data like real gateways would. Why simulate? Because you can’t exactly break a real data center for a thesis. In the simulator I can inject a fault and know exactly when and where it started, which is what makes the measurements trustworthy."),
  p("The cloud side is written as code with AWS CDK, so the whole thing can be rebuilt with one command. IoT Core takes in the sensor messages, Lambda runs the detection, DynamoDB stores the data, and EventBridge with Step Functions runs the repair playbooks. For detection I compare plain thresholds with two ML models, an Isolation Forest and an LSTM autoencoder. And to make sure the models aren’t just good at my own simulator, I also test them on SKAB, a public dataset from a real pump test bench."),
  p("The repair side gets guardrails, because automation on physical equipment can make a bad day worse. Locks stop two playbooks from fighting over the same unit. High-risk actions wait for approval. A circuit breaker switches automation off for a unit that keeps failing."),
  p("Then the testing. I inject faults and compare three ways of working: alerts only, where a person does the fix; thresholds plus automation; and ML plus automation. Eight fault types, each at three severity levels. After that comes the run on real AWS, where I measure latency, push a load test up to 2,000 simulated gateways, and look at the actual bill."),
  p("The methods are quantitative. Eight hypotheses with pass criteria are written down before the final runs (so I can’t move the goalposts later). Results are reported as medians with confidence intervals, and the modes are compared with Mann–Whitney U tests. All the research material comes from the simulator, the public SKAB data and AWS measurements, so there are no interviews and no personal data."),
  p("Rough schedule:", { spacing: { after: 80 } }),
  bullet("**Sep–Oct 2026:** literature review, prototype, offline experiments"),
  bullet("**Nov 2026:** severity tests and validation on real AWS"),
  bullet("**Dec 2026 – Feb 2027:** writing"),
  bullet("**Mar 2027:** final edits, seminar and maturity test"),
  p("Everything (code, data and results) lives in a GitHub repository, so anyone can check my work.", { spacing: { before: 120, after: 140, line: 300 } }),

  field("Relevance of thesis project"),
  prompt("What kind of knowhow and skills can you obtain during the thesis project implementation?"),
  p("Quite a lot, honestly. Data centers are being built at a crazy pace for AI, and people who can connect sensors, cloud and automation are in demand."),
  p("On the technical side I get hands-on time with AWS architecture and IoT connectivity: MQTT, device certificates, device shadows. I’m also learning to design event-driven, serverless systems that cost next to nothing when they’re idle. That turns out to be its own skill, a bit like learning to cook for one person instead of a restaurant."),
  p("Then there’s the machine-learning part. Training anomaly detectors, sure, but maybe more useful is learning when they don’t help. Plain thresholds hold their own more often than you’d expect."),
  p("The part I didn’t expect to value so much is safety thinking. Automating a fan is easy. Automating it so it can’t make things worse takes real design work. And running proper experiments, with statistics rather than a demo that works once, is something I’ll take into any engineering job."),

  field("Commissioning information"),
  p("Leave all six fields empty (company, business ID, registered office, contact person, telephone, e-mail). The topic is self-initiated, so there’s no commissioner. If a company comes on board later, the proposal can be updated."),

  field("Professional specialisation courses and supporting experience"),
  prompt("Professional specialisation courses supporting the thesis completed prior to starting the thesis. Other studies or work experience supporting the thesis."),
  p("[[List your completed courses that fit, e.g. cloud computing, IoT systems, networking, Python programming, data analysis or machine learning. Add any work experience with servers, networks, cloud or building systems.]]"),

  field("Good scientific practice", true),
  p("Before you tick the box, check your university’s rules on AI tools. Parts of the code and documents for this project were made with an AI assistant, so the thesis needs to say so where the guidelines ask for it. Your proposal already promises this in section 11. Since the form says your texts can be run through plagiarism checks, write the thesis chapters themselves in your own words."),
];

const doc = new Document({
  creator: "Mazharul Islam Tusar",
  title: "Thesis topic proposal",
  styles: {
    default: { document: { run: { font: FONT, size: 22, color: INK } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", run: { font: FONT, size: 40, bold: true, color: INK } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 26, bold: true, color: INK }, paragraph: { outlineLevel: 1 } },
    ],
  },
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
    { reference: "rqs", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "RQ%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 540 } } } }] },
  ] },
  sections: [{ properties: { page: { margin: { top: 1300, bottom: 1300, left: 1440, right: 1440 } } }, children }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(process.argv[2], buf);
  console.log("written", process.argv[2], buf.length);
});
