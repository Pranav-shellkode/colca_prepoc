#!/bin/bash

cleanup() {
    echo "Stopping services..."
    kill $BACKEND_PID $FRONTEND_PID
    exit
}

trap cleanup SIGINT SIGTERM

echo "Starting backend..."
python -m backend.server.app &
BACKEND_PID=$!

echo "Starting frontend..."
cd frontend
npm run dev &
FRONTEND_PID=$!

wait