# Stage 1: Build React/Vite application
FROM node:18-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm install

# Build static assets
COPY . .
RUN npm run build

# Stage 2: Serve static assets with Nginx
FROM nginx:1.25-alpine

# Copy build output to Nginx html directory
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy default nginx configuration if customized, or use standard
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
