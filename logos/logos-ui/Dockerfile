# ---- Build Stage ----
FROM node:20-alpine AS builder

# Arbeitsverzeichnis im Container
WORKDIR /app

# Package-Dateien kopieren
COPY logos-ui/package*.json ./

# Abhängigkeiten installieren
RUN npm install -g @angular/cli@19 \
 && npm install

# Restliche Dateien kopieren und App bauen
COPY logos-ui/ ./

RUN ng build --configuration=production --base-href /

# ---- Nginx Stage ----
FROM nginx:alpine

# Angular Build-Dateien in den Standard-Nginx-Webroot kopieren
COPY --from=builder /app/dist/ /usr/share/nginx/html/


FROM nginx:alpine

COPY ./src/   /usr/share/nginx/html/

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
