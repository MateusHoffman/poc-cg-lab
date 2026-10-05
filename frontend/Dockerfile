FROM node:22-bookworm-slim

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

ARG BACKEND_URL=http://backend:8080
ENV BACKEND_URL=$BACKEND_URL
RUN npm run build

ENV NODE_ENV=production
EXPOSE 3000
CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "3000"]
