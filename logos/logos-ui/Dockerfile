FROM node:alpine AS build

WORKDIR /app
RUN npm install -g @angular/cli

# Copy UI
COPY ./logos/logos-ui/ ./
RUN npm ci

# Run production environment
RUN ng build --configuration=production

# Get nginx
FROM nginx:stable AS final

EXPOSE 80

COPY --from=build app/dist/logos-ui/browser  /usr/share/nginx/html
