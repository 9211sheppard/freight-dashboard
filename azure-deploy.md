# Azure Deployment Guide — Freight Intelligence Dashboard

## Prerequisites
- Azure account with active subscription
- Azure CLI installed (`az login`)
- GitHub repo with code pushed

## 1. Create Resource Group (if not exists)
```bash
az group create --name flashcargo-rg --location canadacentral
```

## 2. Create PostgreSQL Database
```bash
az postgres flexible-server create \
  --resource-group flashcargo-rg \
  --name freightdash-db \
  --location canadacentral \
  --admin-user freightadmin \
  --admin-password <STRONG_PASSWORD> \
  --sku-name Standard_B1ms \
  --storage-size 32 \
  --version 16 \
  --public-access 0.0.0.0

# Create the database
az postgres flexible-server db create \
  --resource-group flashcargo-rg \
  --server-name freightdash-db \
  --database-name freightdash
```

## 3. Create App Service
```bash
az appservice plan create \
  --name freightdash-plan \
  --resource-group flashcargo-rg \
  --sku B1 \
  --is-linux

az webapp create \
  --name freightdash \
  --resource-group flashcargo-rg \
  --plan freightdash-plan \
  --runtime "PYTHON:3.12"
```

## 4. Set Environment Variables
```bash
az webapp config appsettings set \
  --name freightdash \
  --resource-group flashcargo-rg \
  --settings \
    PRODUCTION=1 \
    SECRET_KEY="<generate-random-64-char>" \
    DATABASE_URL="postgresql://freightadmin:<PASSWORD>@freightdash-db.postgres.database.azure.com/freightdash?sslmode=require" \
    EMAIL_FROM="admin@flashcargoglobal.com" \
    GRAPH_TENANT_ID="<your-tenant-id>" \
    GRAPH_CLIENT_ID="<your-client-id>" \
    GRAPH_CLIENT_SECRET="<your-client-secret>" \
    STRIPE_SECRET_KEY="<your-stripe-secret>" \
    STRIPE_PUBLISHABLE_KEY="<your-stripe-pub>" \
    STRIPE_WEBHOOK_SECRET="<your-webhook-secret>" \
    STRIPE_PRICE_ID="<your-price-id>" \
    SENTRY_DSN="<your-sentry-dsn>" \
    SCM_DO_BUILD_DURING_DEPLOYMENT=true \
    WEBSITES_PORT=5000
```

## 5. Configure Startup Command
```bash
az webapp config set \
  --name freightdash \
  --resource-group flashcargo-rg \
  --startup-file "gunicorn wsgi:app --workers 2 --bind 0.0.0.0:5000 --timeout 120"
```

## 6. Deploy from GitHub
```bash
az webapp deployment source config \
  --name freightdash \
  --resource-group flashcargo-rg \
  --repo-url https://github.com/<your-username>/contact-dashboard \
  --branch main \
  --manual-integration
```

## 7. Custom Domain (later)
```bash
az webapp config hostname add \
  --webapp-name freightdash \
  --resource-group flashcargo-rg \
  --hostname app.flashcargoglobal.com

# Enable HTTPS
az webapp config ssl bind \
  --name freightdash \
  --resource-group flashcargo-rg \
  --certificate-thumbprint <CERT_THUMB> \
  --ssl-type SNI
```

## 8. Health Check
```bash
az webapp config set \
  --name freightdash \
  --resource-group flashcargo-rg \
  --generic-configurations '{"healthCheckPath": "/health"}'
```

## Estimated Monthly Cost
| Resource | SKU | Cost |
|----------|-----|------|
| App Service | B1 | ~$13/mo |
| PostgreSQL | B1ms | ~$15/mo |
| Custom Domain + SSL | Free with App Service | $0 |
| **Total** | | **~$28/mo** |

At 100 users × $49.99 = $4,999/mo revenue vs $28/mo hosting = 99.4% margin.
