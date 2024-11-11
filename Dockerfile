# Use the official Python 3.8 slim image as the base image
FROM python:3.12-slim

# Set the working directory within the container
WORKDIR /api-flask

# Copy the necessary files and directories into the container
COPY wokky-api.py requirements.txt /api-flask/

# Upgrade pip and install Python dependencies
RUN pip3 install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Expose port 5000 for the Flask application
EXPOSE 5000

# Define the command to run the Flask application using Gunicorn
CMD ["gunicorn", "wokky-api:app", "-b", "0.0.0.0:5000", "-w", "1","--threads","4","--access-logfile", "-", "--capture-output", "--log-level","info"]
