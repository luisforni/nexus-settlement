FROM node:20-alpine AS base
WORKDIR /app
RUN apk add --no-cache dumb-init

FROM base AS deps
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM base AS build
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY tsconfig.json ./
COPY src/ ./src/
RUN npm run build

FROM base AS development
ENV NODE_ENV=development
COPY package.json package-lock.json* ./
RUN npm install --ignore-scripts
COPY tsconfig.json ./
COPY src/ ./src/
EXPOSE 3000
USER node
ENTRYPOINT ["dumb-init", "--"]
CMD ["npx", "ts-node-dev", "--respawn", "--transpile-only", "src/app.ts"]

FROM base AS production
ENV NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
EXPOSE 3000
USER node
ENTRYPOINT ["dumb-init", "--"]
CMD ["node", "dist/app.js"]
