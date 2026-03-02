# 1. Build Stage
FROM node:alpine AS build

WORKDIR /app

# Copy dependency manifests first for layer caching
COPY ./logos/logos-landing/package.json ./logos/logos-landing/package-lock.json ./

# Install dependencies (cached unless package.json/package-lock.json changes)
RUN npm ci

# Copy remaining source
COPY ./logos/logos-landing/ ./

# Build React app (defaults to production mode)
RUN npx expo export --platform web --output-dir landing-build

# 2. Serve Stage (no nginx needed)
FROM node:alpine

# Install a static file server
RUN npm install -g serve

WORKDIR /app

EXPOSE 80

# Copy exported web build from previous stage
COPY --from=build /app/landing-build ./landing-build

# Serve the app
CMD ["serve", "-s", "landing-build", "-l", "80"]
