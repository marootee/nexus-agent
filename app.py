"""
Nexus Agent - Flask Backend
Serves the static site and provides API endpoints
"""

import os
from flask import Flask, render_template, jsonify, request, send_file
from flask_cors import CORS
import logging

app = Flask(__name__, 
    static_folder='static',
    static_url_path='/static'
)

# Enable CORS for API requests
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== Routes ====================

@app.route('/')
def index():
    """Serve the main HTML page"""
    try:
        return send_file('index.html', mimetype='text/html')
    except:
        return "index.html not found", 404

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'healthy',
        'service': 'nexus-agent',
        'version': '1.0.0'
    }), 200

@app.route('/api/contact', methods=['POST'])
def contact():
    """Handle contact form submissions"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'email', 'message']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Here you'd typically save to database or send email
        logger.info(f"New contact: {data['name']} ({data['email']})")
        
        return jsonify({
            'success': True,
            'message': 'Thank you! We will get back to you soon.',
            'data': {
                'name': data['name'],
                'email': data['email']
            }
        }), 201
    
    except Exception as e:
        logger.error(f"Contact form error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/features', methods=['GET'])
def get_features():
    """Get list of features"""
    features = [
        {
            'id': 1,
            'icon': '🤖',
            'title': 'AI-Powered Intelligence',
            'description': 'Leverage cutting-edge language models and machine learning to create agents that understand context and make intelligent decisions.'
        },
        {
            'id': 2,
            'icon': '⚙️',
            'title': 'Modular Architecture',
            'description': 'Build scalable systems with our flexible, plugin-based design. Create custom agents and extend functionality effortlessly.'
        },
        {
            'id': 3,
            'icon': '🚀',
            'title': 'Lightning Fast',
            'description': 'Optimized performance with minimal latency. Process thousands of tasks concurrently with our efficient execution engine.'
        },
        {
            'id': 4,
            'icon': '🔒',
            'title': 'Enterprise Security',
            'description': 'Built with security-first principles. End-to-end encryption, role-based access, and comprehensive audit logging included.'
        },
        {
            'id': 5,
            'icon': '📊',
            'title': 'Real-time Monitoring',
            'description': 'Comprehensive dashboards and logging. Track agent performance, debug issues, and optimize workflows in real-time.'
        },
        {
            'id': 6,
            'icon': '🌍',
            'title': 'Multi-Platform Deploy',
            'description': 'Deploy anywhere - cloud, on-premise, or edge. Works seamlessly across Windows, macOS, Linux, and Docker.'
        }
    ]
    return jsonify({'features': features}), 200

@app.route('/api/pricing', methods=['GET'])
def get_pricing():
    """Get pricing plans"""
    plans = [
        {
            'id': 'starter',
            'name': 'Starter',
            'price': 'Free',
            'period': 'Forever free',
            'featured': False,
            'features': [
                'Up to 5 agents',
                'Community support',
                'Basic monitoring',
                '1GB storage',
                'Open source'
            ]
        },
        {
            'id': 'professional',
            'name': 'Professional',
            'price': '$29',
            'period': 'per month',
            'featured': True,
            'features': [
                'Unlimited agents',
                'Priority support',
                'Advanced analytics',
                '100GB storage',
                'Custom integrations',
                'API access'
            ]
        },
        {
            'id': 'enterprise',
            'name': 'Enterprise',
            'price': 'Custom',
            'period': 'contact sales',
            'featured': False,
            'features': [
                'Unlimited everything',
                '24/7 dedicated support',
                'Custom solutions',
                'Unlimited storage',
                'White-label options',
                'SLA guaranteed'
            ]
        }
    ]
    return jsonify({'plans': plans}), 200

# ==================== Error Handlers ====================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors - serve index.html for SPA"""
    try:
        return send_file('index.html', mimetype='text/html')
    except:
        return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({'error': 'Internal server error'}), 500

# ==================== Main ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
