FROM node:20-alpine

WORKDIR /app

COPY frontend/package.json /app/package.json
RUN npm install

COPY frontend /app

ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE

RUN npm run build

EXPOSE 4173

CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "4173"]
