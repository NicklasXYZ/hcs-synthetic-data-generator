---
hide:
  - navigation
  - toc
---

# Benchmark Dataset

A complete dataset resulting from running the implemented discrete-event simulation can be found [here](https://github.com/NicklasXYZ/hcs-synthetic-data-generator/tree/main/docs/data). It has been obtained by running the simulation code within the code repository. This dataset includes synthetically generated healthcare event sequences modeled after HL7 FHIR R5 resources, including appointments (scheduled, cancelled, or no-show), encounters (actual visits), observations (clinical measurements), and Break The Glass (BTG) events (emergency access).

## Visualizations

To give an overview of the full dataset, a _histogram_ is shown below, illustrating the distribution of aggregated event sequences over 12-hour intervals, categorized according to the classification table available [here](./sim.md). Additionally, a _timeline_ visualization presents a representative sample of the dataset, featuring a subset of practitioners and their associated patients along with all related events. In the timeline visualization, each horizontal (grayscale) band corresponds to a patient's event history, with color-coded bars indicating different event types and their durations.

### Histogram

<div id="visualization-container-histogram"></div>

### Timeline

<div id="visualization-container-timeline"></div>
