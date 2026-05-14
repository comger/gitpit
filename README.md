# GisPit: Hydrological PINN Model for Small Watershed Flood Forecasting

GisPit is a hybrid hydrological forecasting system specifically designed for small watersheds. It combines traditional physical hydrological models (SCS-CN, Unit Hydrograph, Manning's Equation) with modern **Physics-Informed Neural Networks (PINNs)** to achieve real-time, high-accuracy water level predictions. 

The architecture is lightweight and optimized for edge-computing environments (e.g., 1 TOPs NPUs), capable of performing millisecond-level online fine-tuning and inference.

## Key Features

* **Hybrid Physical-AI Architecture**: 
  * Replaces empirical static parameters with an LSTM-based parameter-predicting neural network that outputs dynamic physical corrections ($\Delta CN, \Delta n, \alpha$).
  * The physical layer is fully differentiable using PyTorch tensors, allowing gradients to flow back from physical mass conservation and gradient-matching loss functions.
* **Global Pre-training & Fast Adaptation**: 
  * Supports wide-table CSV imports for multi-site cross-training.
  * Treats static basin features ($A, L, S_0, CN_0$) as embeddings, enabling the model to generalize across watersheds.
* **Edge-Optimized**: Operates flawlessly on lightweight hardware for real-time data assimilation without massive GPU dependencies.
* **HTT Data Governance**: Implements a robust "Hydro-Triple-Trust" (HTT) data governance mechanism to intercept sensor noise and physical anomalies before they impact the model.

## Technology Stack

* **Backend**: Python 3.9+, FastAPI, PyTorch, Pandas, SQLite
* **Frontend**: Vanilla HTML5/CSS3/JS, ECharts (for visualization)

## System Structure

* `backend/`
  * `main.py`: FastAPI server entry point.
  * `pinn_model.py`: PyTorch-based core engine including the LSTM NN block, Differentiable Physics Layer, and custom loss functions.
  * `routing_engine.py`: Traditional SCS-CN and unit hydrograph physics forecaster.
  * `csv_importer.py` & `template_gen.py`: Data ingestion pipelines and template generation supporting the PINN wide-table format.
  * `db.py`: SQLite database schema and migrations.
* `frontend/`
  * Dashboard UI for managing forecast stations, uploading CSV data, triggering online training, and viewing real-time hydrograph visualizations.

## Quick Start

1. **Install Dependencies**:
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Run the Backend Service**:
   ```bash
   python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

3. **Open the Dashboard**:
   Open `frontend/index.html` in your web browser.

## Data Template Format
The system supports importing historical sensor data via CSV with the following columns:
`timestamp, rainfall_mm, h_up_m, water_level_m, flow_m3s`

The backend dynamically joins this with static physical watershed parameters stored in the database before feeding it into the PINN engine.
