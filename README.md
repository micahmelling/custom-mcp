# custom-mcp

This repo provide a very simple MCP server in app/app.py. The focus is more on functionality than utility (i.e. 
we want to show how to set the proper structure and protocols for MCP).

The app can be deployed on AWS via Pulumi. In AWS, you'll need to have purchased a domain and set up an SSL cert for it.
Likewise, you will need to have some basic networking set up (VPC, subnets). The Pulumi script will automatically 
build your Docker image and push it to ECR (though it only uses the latest tag for ease. The app does not follow all 
best practices (does not leverage private subnets, does not have end to end encryption). It is a good starting
place for iteration. Likewise, the Dockerfile is basic and should be improved (e.g., do not run the app as root).

Overall, the goal is to get you going with a workable app. 
