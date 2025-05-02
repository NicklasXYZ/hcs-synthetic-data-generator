---
hide:
  - navigation
  - toc
---

# Event Sequence Visualization

A complete dataset resulting from running the implemented discrete-event simulation can be found [here](https://github.com/NicklasXYZ/hcs-synthetic-data-generator/tree/main/docs/data). It has been obtained by running the simulation code within the code repository. This dataset includes synthetically generated healthcare event sequences modeled after HL7 FHIR R5 resources, including appointments (scheduled, cancelled, or no-show), encounters (actual visits), observations (clinical measurements), and Break The Glass (BTG) events (emergency access).

For demonstration purposes, a sample of this dataset is displayed below through a timeline visualization. The sample includes a subset of practitioners and their associated patients, along with all relevant events.

The visualization displays synthetically generated healthcare event sequences. Each horizontal (grayscale) band represents a patient's event history, with color-coded bars indicating event types and durations.

<div id="visualization-container"></div>
