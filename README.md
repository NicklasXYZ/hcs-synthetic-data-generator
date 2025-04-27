# Setup

```bash
conda create -n ids python=3.11
conda activate ids
pip install simpy pandas fhir.resources sqlmodel Faker mkdocs-material  mkdocs-minify-plugin
```


# Synthetic Data Generation

```bash
# Generate synthetic data:
python simulation.py

# Export to json
python export_data.py

# Visualize the simulated data 
mkdocs serve
# --> navigate to localhost:8000/vis
```