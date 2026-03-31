# 1. Build Stage
FROM node:alpine AS build

WORKDIR /app

# Copy dependency manifests and npm config first for layer caching
# .npmrc is copied separately with a wildcard so the build doesn't fail if it's absent
COPY package.json package-lock.json ./
COPY .npmr[c] ./

# Install dependencies (cached unless package.json/package-lock.json changes)
RUN npm ci

# Copy remaining source
COPY . ./

# Build React app (defaults to production mode)
RUN npx expo export --platform web --output-dir web-build

# 2. Serve Stage (no nginx needed)
FROM node:alpine

# Install a static file server
RUN npm install -g serve

WORKDIR /app

EXPOSE 80

# Copy exported web build from previous stage
COPY --from=build /app/web-build ./web-build

# Serve the app
CMD ["serve", "-s", "web-build", "-l", "80"]
