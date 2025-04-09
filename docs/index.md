---
hide:
  - navigation
  - toc
---

# Code Repository

The code repository [hcs-synthetic-data-generator](https://github.com/NicklasXYZ/hcs-synthetic-data-generator) contains code for running a discrete-event simulation modeling patient-practitioner interactions in a healthcare system, generating synthetic FHIR R5 resources including:

- Appointments (scheduled, cancelled, no-shows)
- Encounters (actual visits)
- Clinical observations
- Break The Glass (BTG) emergency access events

The simulation is designed to produce realistic event sequences that can be classified as either normal or anomalous patterns of healthcare system usage.

The resulting dataset (located [here](https://github.com/NicklasXYZ/hcs-synthetic-data-generator/docs/data)) obtained by running the simulation code within the repository is displayed below.

## Event Sequence Visualization

The timeline visualization below displays synthetically generated healthcare event sequences modeled after HL7 FHIR R5 resources, including appointments (scheduled, cancelled, or no-show), encounters (actual visits), observations (clinical measurements), and Break The Glass (BTG) events (emergency access). Each horizontal (grayscale) band represents a patient's event history, with color-coded bars indicating event types and durations.

<div id="visualization-container"></div>
