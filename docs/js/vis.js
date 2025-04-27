document.addEventListener("DOMContentLoaded", function () {
  const path = window.location.pathname;
    
  // Remove trailing slash if needed
  const normalizedPath = path.endsWith("/") ? path.slice(0, -1) : path;

  console.log("Current path:", normalizedPath);

  if (normalizedPath.endsWith("/vis")) {
    // Load data
    Promise.all([
      fetch("../data/patients.json").then((r) => r.json()),
      fetch("../data/practitioners.json").then((r) => r.json()),
      fetch("../data/events.json").then((r) => r.json()),
    ])
      .then(([patients, practitioners, events]) => {
        // Create lookup maps
        const patientMap = new Map(patients.map((p) => [p.id, p]));
        const practitionerMap = new Map(practitioners.map((p) => [p.id, p]));
  
        // Store data with valid references only
        window.vizData = {
          patientMap,
          practitionerMap,
          events: events.filter(
            (e) =>
              patientMap.has(e.patient_id) &&
              practitionerMap.has(e.practitioner_id)
          ),
          patients,
          practitioners,
        };
  
        // Create controls - simplified to just practitioner selection
        const controls = document.createElement("div");
        controls.className = "controls";
  
        controls.innerHTML = `
        <div class="control-group">
            <label for="practitioner-select">Filter by Practitioner:</label>
            <select id="practitioner-select" class="form-select">
                ${practitioners
                  .sort((a, b) => a.last_name.localeCompare(b.last_name))
                  .map(
                    (p, index) => `
                    <option value="${p.id}" ${index === 0 ? "selected" : ""}>
                        Dr. ${p.last_name} (${p.specialty || "General"})
                    </option>
                `
                  )
                  .join("")}
            </select>
        </div>
    `;
        // Create visualization container
        const vizContainer = document.createElement("div");
        vizContainer.innerHTML = `
              <div id="timeline-plot" class="plot-container"></div>
              <div id="event-details" class="details-panel"></div>
          `;
  
        // Add to page
        document
          .querySelector("#visualization-container")
          .append(controls, vizContainer);
  
        // Initialize visualization (with first practitioner selected by default)
        const firstPractitionerId = practitioners.sort((a, b) =>
          a.last_name.localeCompare(b.last_name)
        )[0].id;
        document.getElementById("practitioner-select").value =
          firstPractitionerId;
  
        updateVisualization();
  
        // Auto-update when practitioner selection changes
        document
          .getElementById("practitioner-select")
          .addEventListener("change", updateVisualization);
      })
      .catch((error) => {
        console.error("Error loading data:", error);
        document.getElementById("visualization-container").innerHTML = `
              <div class="error">
                  Failed to load data. Please check your data files and try again.
                  <pre>${error.message}</pre>
              </div>
          `;
      });
  
    function updateVisualization() {
      const { patientMap, practitionerMap, events, practitioners } =
        window.vizData;
  
      // Get current filter values
      // const practitionerId = document.getElementById("practitioner-select").value;
      const selectedTypes = ["appointment", "encounter", "observation", "btg"];
  
      // Get current filter values
      const practitionerId = document.getElementById("practitioner-select").value;
      const currentPractitioner = practitionerId
        ? practitionerMap.get(practitionerId)
        : null;
  
      // Create title based on selection
      let plotTitle = "Patient Timeline";
      if (currentPractitioner) {
        plotTitle = `Patient Timeline - Dr. ${currentPractitioner.last_name} (ID: ${currentPractitioner.id})`;
      } else {
        plotTitle = "Patient Timeline - All Practitioners";
      }
  
      // Filter events
      const filteredEvents = events.filter((e) => {
        return (
          (!practitionerId || e.practitioner_id === practitionerId) &&
          selectedTypes.includes(e.type)
        );
      });
  
      // Group by patient-practitioner pairs
      const pairs = {};
      filteredEvents.forEach((e) => {
        const key = `${e.patient_id}|${e.practitioner_id}`;
        if (!pairs[key]) {
          const patient = patientMap.get(e.patient_id);
          const practitioner = practitionerMap.get(e.practitioner_id);
          pairs[key] = {
            patient,
            practitioner,
            events: [],
          };
        }
        pairs[key].events.push(e);
      });
  
      // Sort pairs consistently
      const sortedPairs = Object.values(pairs).sort((a, b) => {
        const patientCompare =
          `${a.patient.last_name} ${a.patient.first_name}`.localeCompare(
            `${b.patient.last_name} ${b.patient.first_name}`
          );
        if (patientCompare !== 0) return patientCompare;
        return a.practitioner.last_name.localeCompare(b.practitioner.last_name);
      });
  
      // Visualization setup
      const colors = {
        appointment: "#1f77b4",
        encounter: "#ff7f0e",
        observation: "#2ca02c",
        btg: "#d62728",
        groupBgOdd: "rgba(240, 240, 240, 0.25)",
        groupBgEven: "rgba(240, 240, 240, 0.75)",
        groupBorder: "rgba(150, 150, 150, 0.7)",
      };
  
      const plotData = [];
      const yCategories = [];
      const shapes = [];
      const typeOrder = ["appointment", "encounter", "observation", "btg"];
      const rowsPerGroup = 4; // Fixed number of rows per group
      const rowHeight = 1; // Height unit per row
      const groupHeight = rowsPerGroup * rowHeight;
  
      // Calculate positions and create elements
      sortedPairs.forEach((pair, groupIndex) => {
        const groupStartY = groupIndex * (groupHeight + 0.0) - 0.5; // 0.2 for small gap between groups
  
        yCategories.push(`${pair.patient.first_name} ${pair.patient.last_name}`);
  
        // Add background shape (fixed size for all groups)
        shapes.push({
          type: "rect",
          x0: 0,
          x1: 1,
          y0: groupStartY,
          y1: groupStartY + groupHeight,
          xref: "paper",
          yref: "y",
          fillcolor:
            groupIndex % 2 === 0 ? colors.groupBgEven : colors.groupBgOdd,
          line: { width: 0 },
          layer: "below",
        });
  
        // Add group border (fixed size)
        shapes.push({
          type: "rect",
          x0: 0,
          x1: 1,
          y0: groupStartY,
          y1: groupStartY + groupHeight,
          xref: "paper",
          yref: "y",
          fillcolor: "rgba(0,0,0,0)",
          line: {
            color: colors.groupBorder,
            width: 1,
            dash: "dot",
          },
          layer: "below",
        });
  
        // Create all type labels (even if no events exist)
        typeOrder.forEach((type, typeIndex) => {
          const yPos = groupStartY + typeIndex * rowHeight + rowHeight / 2;
  
          // Type label
          plotData.push({
            x: [null],
            y: [yPos],
            mode: "text",
            text: [type.charAt(0).toUpperCase() + type.slice(1)],
            textposition: "right",
            showlegend: false,
            hoverinfo: "none",
            textfont: {
              color: colors[type],
              size: 12,
            },
          });
        });
  
        // Add actual events
        pair.events.forEach((event) => {
          const typeIndex = typeOrder.indexOf(event.type);
          if (typeIndex === -1) return;
  
          const yPos = groupStartY + typeIndex * rowHeight + rowHeight / 2;
          const isInstantEvent = !event.start && !event.end && event.timestamp;
  
          if (isInstantEvent) {
            // Instant event - single point
            plotData.push({
              x: [event.timestamp],
              y: [yPos],
              name: event.type.charAt(0).toUpperCase() + event.type.slice(1),
              type: "scatter",
              mode: "markers",
              marker: {
                symbol: "circle",
                size: 12,
                color: colors[event.type],
                line: {
                  color: "white",
                  width: 2,
                },
              },
              hoverlabel: {
                namelength: -1,
                bgcolor: "white",
                bordercolor: "#aaa",
                font: { size: 12 },
              },
              hoverinfo: "text",
              hovertext: createHoverText(event, pair.patient, pair.practitioner),
              customdata: [event],
              legendgroup: event.type,
              showlegend:
                plotData.filter(
                  (d) => d.legendgroup === event.type && d.mode === "markers"
                ).length === 0,
              layer: "above",
            });
          } else {
            // Duration event - line with markers
            const start = event.start || event.timestamp;
            const end =
              event.end ||
              (event.start
                ? new Date(new Date(event.start).getTime() + 1000 * 60 * 30)
                : new Date(new Date(event.timestamp).getTime() + 1000 * 60 * 30));
  
            plotData.push({
              x: [start, end],
              y: [yPos, yPos],
              name: event.type.charAt(0).toUpperCase() + event.type.slice(1),
              type: "scatter",
              mode: "lines+markers",
              line: {
                color: colors[event.type],
                width: 8,
                shape: "hv",
              },
              marker: {
                symbol: event.end ? "none" : "circle",
                size: 10,
                color: colors[event.type],
                line: {
                  color: "white",
                  width: 2,
                },
              },
              hoverlabel: {
                namelength: -1,
                bgcolor: "white",
                bordercolor: "#aaa",
                font: { size: 12 },
              },
              hoverinfo: "text",
              hovertext: createHoverText(event, pair.patient, pair.practitioner),
              customdata: [event],
              legendgroup: event.type,
              showlegend:
                plotData.filter(
                  (d) =>
                    d.legendgroup === event.type && d.mode === "lines+markers"
                ).length === 0,
              layer: "above",
            });
          }
        });
      });
  
      // Calculate total height needed (50px per row unit)
      const totalHeight = sortedPairs.length * (groupHeight + 0.2) * 20;
  
      console.log(sortedPairs.length * 4);
  
      // Create plot with fixed group sizes
      const layout = {
        title: {
          text: plotTitle,
          x: 0.5, // Center the title
          xanchor: "center",
        },
        height: totalHeight,
        margin: {
          l: 100,
          r: 50,
          b: 100,
          t: 75,
          pad: 8,
        },
        xaxis: {
          type: "date",
          title: "Timeline",
          rangeslider: { visible: false },
          showspikes: false,
          showgrid: true,
        },
        yaxis: {
          type: "category",
          automargin: true,
          title: "Patients",
          tickmode: "array",
          tickvals: sortedPairs.map(
            (_, i) => i * (groupHeight + 0.0) + groupHeight / 2
          ),
          ticktext: sortedPairs.map(
            (pair) => `${pair.patient.first_name} ${pair.patient.last_name}`
          ),
          showgrid: false,
          fixedrange: true,
          range: [
            -rowsPerGroup,
            sortedPairs.length * rowsPerGroup + rowsPerGroup,
          ],
        },
        shapes: shapes,
        hovermode: "closest",
        showlegend: true,
        hoverlabel: {
          bgcolor: "white",
          bordercolor: "#aaa",
          font: { size: 12 },
        },
        plot_bgcolor: "rgba(0,0,0,0)",
        paper_bgcolor: "rgba(0,0,0,0)",
      };
  
      const config = {
        responsive: true,
        displayModeBar: false,
        scrollZoom: true,
      };
  
      Plotly.newPlot("timeline-plot", plotData, layout, config);
  
      function createHoverText(event, patient, practitioner) {
        const formatDate = (dateStr) =>
          dateStr ? new Date(dateStr).toLocaleString() : "";
  
        const createRow = (label, value) =>
          `<span style="font-family:monospace;white-space:pre">` +
          `${label.padEnd(10)}${value}` +
          `</span>`;
  
        const timeInfo =
          event.timestamp && !event.start && !event.end
            ? createRow("Time:", formatDate(event.timestamp))
            : [
                event.start && createRow("Start:", formatDate(event.start)),
                event.end && createRow("End:", formatDate(event.end)),
              ]
                .filter(Boolean)
                .join("<br>");
  
        const parts = [
          `<b>${event.type.toUpperCase()}</b>`,
          createRow("Patient:", `${patient.first_name} ${patient.last_name}`),
          createRow("Provider:", `Dr. ${practitioner.last_name}`),
          timeInfo,
          event.code && createRow("Code:", event.code),
          event.value && createRow("Value:", event.value),
          event.status && createRow("Status:", event.status),
        ]
          .filter(Boolean)
          .join("<br>");
  
        return parts;
      }
    }

  }

});
