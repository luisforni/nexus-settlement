FROM node:20-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json tsconfig.json ./
RUN npm ci --ignore-scripts
COPY src ./src
RUN npm run build


FROM node:20-alpine AS development
WORKDIR /app
COPY package*.json tsconfig.json ./
RUN npm install --ignore-scripts
COPY src ./src
ENV NODE_ENV=development
EXPOSE 8003
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser
CMD ["npx", "ts-node-dev", "--respawn", "--transpile-only", "src/app.ts"]

FROM node:20-alpine AS production
LABEL maintainer="nexus-settlement"
WORKDIR /app
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser

COPY --from=deps --chown=appuser:appgroup /app/node_modules ./node_modules
COPY --from=build --chown=appuser:appgroup /app/dist ./dist

ENV NODE_ENV=production
EXPOSE 8003
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:8003/health', r => r.statusCode === 200 ? process.exit(0) : process.exit(1))"

CMD ["node", "dist/app.js"]
