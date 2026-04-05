@echo off
echo Starting GFLN Live Demo on port 5003...
cd /d "%~dp0"
set PORT=5003
set TMS_MASTER_USERNAME=demo
set TMS_MASTER_PASSWORD=gfln2024
set TMS_MASTER_DB_PATH=data/gfln_demo.db
set TMS_MASTER_BRAND_NAME=Georgian Freight Lines
set TMS_DISABLE_NOTIFICATION_SCHEDULER=0
python app.py
