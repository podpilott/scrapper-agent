#!/bin/bash
# Test script to trigger auto-ban by exceeding rate limits
# Usage: ./test_auto_ban.sh <TOKEN>

API_URL="https://scrapper-staging.kubeletto.app"

if [ -z "$1" ]; then
    echo "Usage: $0 <BEARER_TOKEN>"
    echo ""
    echo "Get your token from browser DevTools:"
    echo "1. Open https://leadgen.benelabs.tech"
    echo "2. Open DevTools > Network tab"
    echo "3. Make any API request"
    echo "4. Copy the 'authorization' header value (without 'Bearer ')"
    exit 1
fi

TOKEN="$1"

echo "=== Auto-Ban Test Script ==="
echo "API: $API_URL"
echo ""

# Counter for tracking
success=0
rate_limited=0

echo "Making rapid requests to trigger rate limiting..."
echo "Rate limit: 10/min, Auto-ban threshold: 20 violations"
echo ""

for i in {1..35}; do
    # Get full response with status code
    http_response=$(curl -s -w "HTTPSTATUS:%{http_code}" -X POST "$API_URL/api/query/enhance" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $TOKEN" \
        -d '{"query": "test query"}')

    # Extract body and status
    http_body=$(echo "$http_response" | sed -e 's/HTTPSTATUS\:.*//g')
    http_status=$(echo "$http_response" | tr -d '\n' | sed -e 's/.*HTTPSTATUS://')

    case $http_status in
        200)
            ((success++))
            echo "[$i] ✅ 200 OK - Success"
            ;;
        429)
            ((rate_limited++))
            echo "[$i] ⚠️  429 Rate Limited - Violations: $rate_limited"
            ;;
        403)
            echo "[$i] 🚫 403 BANNED!"
            echo "Response: $http_body"
            echo ""
            echo "=== AUTO-BAN TRIGGERED ==="
            echo "Total requests: $i"
            echo "Successful: $success"
            echo "Rate limited: $rate_limited"
            exit 0
            ;;
        401)
            echo "[$i] ❌ 401 Unauthorized - Token expired. Get a new one from the browser."
            exit 1
            ;;
        *)
            echo "[$i] ❓ $http_status - $http_body"
            ;;
    esac

    # Small delay
    sleep 0.05
done

echo ""
echo "=== Test Complete ==="
echo "Successful: $success"
echo "Rate limited: $rate_limited"
echo ""
echo "If not banned yet, you have $rate_limited violations recorded."
echo "Run again to accumulate more violations (need 20+ for 1-hour ban)."
