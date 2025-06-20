document.addEventListener("DOMContentLoaded", async () => {
  const path = window.location.pathname.replace(/\/$/, "");

  if (!path.endsWith("/vis")) return;

  try {
    const [patients, practitioners, events] = await loadTimelineData();
    initializeGlobalData(patients, practitioners, events);
    setupControls(practitioners);
    renderTimelineVisualization();
    addControlListeners();

    await renderHistogram();
  } catch (error) {
    showError("visualization-container-timeline", error, "data");
  }
});

// --- Data Loading ---
async function loadTimelineData() {
  const [patients, practitioners, events] = await Promise.all([
    fetchJSON("../data/patients_sample.json"),
    fetchJSON("../data/practitioners_sample.json"),
    fetchJSON("../data/events_sample.json"),
  ]);
  return [patients, practitioners, events];
}

function fetchJSON(path) {
  return fetch(path).then((r) => {
    if (!r.ok) throw new Error(`Failed to fetch ${path}`);
    return r.json();
  });
}

function initializeGlobalData(patients, practitioners, events) {
  window.vizData = {
    patientMap: new Map(patients.map((p) => [p.id, p])),
    practitionerMap: new Map(practitioners.map((p) => [p.id, p])),
    events,
    practitioners,
  };
}

// --- Controls + DOM Setup ---
function setupControls(practitioners) {
  const container = document.querySelector("#visualization-container-timeline");
  const controls = document.createElement("div");
  controls.className = "controls";
  controls.innerHTML = `
    <div class="control-group">
      <label for="practitioner-select">Filter by Practitioner:</label>
      <select id="practitioner-select" class="form-select">
        ${practitioners
          .sort((a, b) => a.last_name.localeCompare(b.last_name))
          .map(
            (p, i) => `
            <option value="${p.id}" ${i === 0 ? "selected" : ""}>
              Dr. ${p.last_name} (${p.specialty || "General"})
            </option>`
          )
          .join("")}
      </select>
    </div>
  `;

  const vizContainer = document.createElement("div");
  vizContainer.innerHTML = `
    <div id="timeline-plot" class="plot-container"></div>
    <div id="event-details" class="details-panel"></div>
  `;

  container.append(controls, vizContainer);
}

function addControlListeners() {
  document
    .getElementById("practitioner-select")
    .addEventListener("change", renderTimelineVisualization);
}

// --- Visualization Logic ---
function renderTimelineVisualization() {
  const { patientMap, practitionerMap, events, practitioners } = window.vizData;
  const practitionerId = document.getElementById("practitioner-select").value;
  const selectedTypes = [
    "Appointment",
    "Encounter",
    "Observation",
    "AuditEvent",
  ];
  const currentPractitioner = practitionerMap.get(practitionerId);
  const plotTitle = currentPractitioner
    ? `Patient Timeline - Dr. ${currentPractitioner.last_name} (ID: ${currentPractitioner.id})`
    : "Patient Timeline - All Practitioners";

  // Group, sort, and prepare data
  const filteredEvents = events.filter(
    (e) =>
      (!practitionerId || e.practitioner_id === practitionerId) &&
      selectedTypes.includes(e.type)
  );
  const groupedPairs = groupEventsByPatientPractitioner(
    filteredEvents,
    patientMap,
    practitionerMap
  );
  const { plotData, shapes, yAxisConfig, totalHeight } = buildPlotData(
    groupedPairs,
    selectedTypes
  );

  const layout = {
    title: { text: plotTitle, x: 0.5, xanchor: "center" },
    height: totalHeight,
    margin: { l: 100, r: 50, b: 100, t: 75, pad: 8 },
    xaxis: {
      type: "date",
      title: "Timeline",
      rangeslider: { visible: false },
      showgrid: true,
    },
    yaxis: yAxisConfig,
    shapes,
    hovermode: "closest",
    showlegend: true,
    plot_bgcolor: "rgba(0,0,0,0)",
    paper_bgcolor: "rgba(0,0,0,0)",
  };

  const config = { responsive: true, displayModeBar: false, scrollZoom: true };
  Plotly.newPlot("timeline-plot", plotData, layout, config);
}

// --- Timeline Helpers ---
function groupEventsByPatientPractitioner(events, patientMap, practitionerMap) {
  const pairs = {};
  events.forEach((e) => {
    const key = `${e.patient_id}|${e.practitioner_id}`;
    if (!pairs[key]) {
      const patient = patientMap.get(e.patient_id);
      const practitioner = practitionerMap.get(e.practitioner_id);
      if (patient && practitioner) {
        pairs[key] = { patient, practitioner, events: [] };
      }
    }
    pairs[key]?.events.push(e);
  });
  return Object.values(pairs).sort((a, b) =>
    `${a.patient.last_name} ${a.patient.first_name}`.localeCompare(
      `${b.patient.last_name} ${b.patient.first_name}`
    )
  );
}

function buildPlotData(pairs, typeOrder) {
  const colors = {
    Appointment: "#1f77b4",
    Encounter: "#ff7f0e",
    Observation: "#2ca02c",
    AuditEvent: "#d62728",
    groupBgOdd: "rgba(240, 240, 240, 0.25)",
    groupBgEven: "rgba(240, 240, 240, 0.75)",
    groupBorder: "rgba(150, 150, 150, 0.7)",
  };

  const plotData = [],
    shapes = [],
    yCategories = [];
  const rowHeight = 1,
    rowsPerGroup = typeOrder.length;
  const groupHeight = rowHeight * rowsPerGroup;

  pairs.forEach((pair, i) => {
    const yBase = i * groupHeight - 0.5;
    yCategories.push(`${pair.patient.first_name} ${pair.patient.last_name}`);

    shapes.push(
      ...[
        {
          type: "rect",
          xref: "paper",
          yref: "y",
          layer: "below",
          x0: 0,
          x1: 1,
          y0: yBase,
          y1: yBase + groupHeight,
          fillcolor: i % 2 === 0 ? colors.groupBgEven : colors.groupBgOdd,
          line: { width: 0 },
        },
        {
          type: "rect",
          xref: "paper",
          yref: "y",
          layer: "below",
          x0: 0,
          x1: 1,
          y0: yBase,
          y1: yBase + groupHeight,
          fillcolor: "rgba(0,0,0,0)",
          line: { color: colors.groupBorder, width: 1, dash: "dot" },
        },
      ]
    );

    typeOrder.forEach((type, idx) => {
      const yPos = yBase + idx * rowHeight + rowHeight / 2;
      plotData.push({
        x: [null],
        y: [yPos],
        mode: "text",
        text: [type],
        showlegend: false,
        textfont: { color: colors[type], size: 12 },
        hoverinfo: "none",
      });
    });

    for (const event of pair.events) {
      const idx = typeOrder.indexOf(event.type);
      const yPos = yBase + idx * rowHeight + rowHeight / 2;
      const isInstant = !event.start && !event.end && event.timestamp;

      const legendAlreadyShown = plotData.some(
        (d) =>
          d.legendgroup === event.type &&
          d.mode === (isInstant ? "markers" : "lines+markers")
      );

      const trace = {
        x: isInstant
          ? [event.timestamp]
          : [
              event.start || event.timestamp,
              event.end ||
                new Date(
                  new Date(event.start || event.timestamp).getTime() + 1800000
                ),
            ],
        y: isInstant ? [yPos] : [yPos, yPos],
        mode: isInstant ? "markers" : "lines+markers",
        type: "scatter",
        name: event.type,
        marker: {
          symbol: isInstant ? "circle" : "none",
          size: 12,
          color: colors[event.type],
          line: { color: "white", width: 2 },
        },
        line: isInstant
          ? undefined
          : {
              color: colors[event.type],
              width: 8,
              shape: "hv",
            },
        hovertext: createHoverText(event, pair.patient, pair.practitioner),
        hoverinfo: "text",
        legendgroup: event.type,
        showlegend: !legendAlreadyShown,
      };

      plotData.push(trace);
    }
  });

  const totalHeight = pairs.length * (groupHeight + 0.2) * 20;
  return {
    plotData,
    shapes,
    totalHeight,
    yAxisConfig: {
      type: "category",
      automargin: true,
      title: "Patients",
      tickvals: pairs.map((_, i) => i * groupHeight + groupHeight / 2),
      ticktext: yCategories,
      showgrid: false,
      fixedrange: true,
      range: [-rowsPerGroup, pairs.length * rowsPerGroup + rowsPerGroup],
    },
  };
}

function createHoverText(event, patient, practitioner) {
  const format = (d) => (d ? new Date(d).toLocaleString() : "");
  const info = [
    `<b>${event.type}</b>`,
    `Patient: ${patient.first_name} ${patient.last_name}`,
    `Provider: Dr. ${practitioner.last_name}`,
    event.timestamp && `Time: ${format(event.timestamp)}`,
    event.start && `Start: ${format(event.start)}`,
    event.end && `End: ${format(event.end)}`,
    event.code && `Code: ${event.code}`,
    event.value && `Value: ${event.value}`,
    event.status && `Status: ${event.status}`,
    event.data?.event_type && `Type: ${event.data.event_type}`,
    event.data?.purpose && `Purpose: ${event.data.purpose}`,
  ].filter(Boolean);

  return info.join("<br>");
}

// --- Histogram Rendering ---
async function renderHistogram() {
  try {
    const jsonData = await fetchJSON("../data/histogram_data-12H.json");
    const tableIds = Object.values(jsonData.table_id);
    const counts = Object.values(jsonData.count);
    const labels = Object.values(jsonData.label);
    const uniqueLabels = [...new Set(labels)];

    const grouped = Object.fromEntries(
      uniqueLabels.map((label) => [label, Array(tableIds.length).fill(0)])
    );
    labels.forEach((label, i) => (grouped[label][i] = counts[i]));

    const traces = uniqueLabels.map((label) => ({
      x: tableIds.map((id) => `ID: ${id}`),
      y: grouped[label],
      name: label,
      type: "bar",
      text: grouped[label].map((c) => (c > 0 ? `${c}` : "")),
      textposition: "outside",
      textfont: { size: 12, color: "#000" },
      marker: { color: label === "Anomaly" ? "#d62728" : "#2ca02c" },
    }));

    const layout = {
      title: {
        text: "Histogram of Aggregated Event Sequences (12-hour Intervals)",
        x: 0.5,
        xanchor: "center",
      },
      barmode: "stack",
      xaxis: { title: "Time Window ID" },
      yaxis: { title: "Number of Sequences" },
      margin: { l: 60, r: 30, b: 60, t: 60 },
      plot_bgcolor: "rgba(0,0,0,0)",
      paper_bgcolor: "rgba(0,0,0,0)",
    };

    Plotly.newPlot("visualization-container-histogram", traces, layout, {
      responsive: true,
      displayModeBar: false,
    });
  } catch (err) {
    showError("visualization-container-histogram", err, "histogram");
  }
}

// --- Error Handling ---
function showError(containerId, error, label) {
  console.error(`Error loading ${label} data:`, error);
  document.getElementById(containerId).innerHTML = `
    <div class="error">
      Failed to load ${label} data.
      <pre>${error.message}</pre>
    </div>
  `;
}
