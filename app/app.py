import uvicorn
import httpx
import hashlib
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import JSONResponse
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent


server = Server("mcp-poc")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_weather",
            description="Fetches the current weather for a given latitude and longitude.",
            inputSchema={
                "type": "object",
                "properties": {
                    "latitude": {"type": "number", "description": "Latitude of the location"},
                    "longitude": {"type": "number", "description": "Longitude of the location"}
                },
                "required": ["latitude", "longitude"]
            }
        ),
        Tool(
            name="calculate_hash",
            description="Calculates the SHA-256 cryptographic hash of the provided text.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to hash"}
                },
                "required": ["text"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    if name == "get_weather":
        lat = arguments.get("latitude")
        lon = arguments.get("longitude")
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"

        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        weather_info = data.get("current_weather", {})
        return [TextContent(
            type="text",
            text=f"Current temperature is {weather_info.get('temperature')}°C with wind speed {weather_info.get('windspeed')} km/h."
        )]

    elif name == "calculate_hash":
        text = arguments.get("text", "")
        hash_hex = hashlib.sha256(text.encode('utf-8')).hexdigest()
        return [TextContent(type="text", text=f"SHA-256 Hash: {hash_hex}")]

    raise ValueError(f"Unknown tool: {name}")


sse = SseServerTransport("/messages")
app = Starlette(debug=True)


async def sse_handler(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def messages_handler(request: Request):
    await sse.handle_post_message(request.scope, request.receive, request._send)


async def healthcheck_handler(request: Request):
    return JSONResponse({"status": "ok"})


app.routes.append(Route("/sse", endpoint=sse_handler))
app.routes.append(Route("/messages", endpoint=messages_handler, methods=["POST"]))
app.routes.append(Route("/health", endpoint=healthcheck_handler))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
