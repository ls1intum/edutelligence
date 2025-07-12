# 1. Build Stage
FROM node:alpine AS build

WORKDIR /app

# Copy React UI source code
COPY ./logos/logos-ui/ ./

# Install dependencies
RUN npm install @react-native-picker/picker
RUN npm ci

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
