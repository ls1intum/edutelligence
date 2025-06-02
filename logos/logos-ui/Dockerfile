# 1. Build Stage
FROM node:alpine AS build

WORKDIR /app

# Copy React UI source code
COPY ./logos/logos-ui/ ./

# Install dependencies
RUN npm ci

# Build React app (defaults to production mode)
RUN npx expo export --platform web --output-dir web-build

# 2. NGINX Stage
FROM nginx:stable AS final

EXPOSE 80

# Copy build output to NGINX html directory
COPY --from=build /app/web-build /usr/share/nginx/html

# Optional: Replace default nginx.conf if needed
# COPY ./nginx.conf /etc/nginx/nginx.conf
