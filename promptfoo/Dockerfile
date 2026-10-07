FROM node:24-alpine
WORKDIR /app
# Install bash since the run script uses bash features
RUN apk add --no-cache bash curl
COPY package.json package-lock.json* ./
RUN npm ci --production
COPY . ./
RUN chmod +x ./run_promptfoo_eval.sh
ENTRYPOINT ["/bin/bash","-c","./run_promptfoo_eval.sh"]
