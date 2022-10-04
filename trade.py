from flask import Flask, request, abort, render_template, jsonify
from pybit import inverse_perpetual
import config
import json
import time
import base64
import boto3
import datetime

currentDate = datetime.date.today()
month = currentDate.strftime("%B")

print(currentDate)
print(month)


keys = config.keys


session = inverse_perpetual.HTTP(
    endpoint='https://api.bybit.com',
    api_key=keys[1]['api_key'],
    api_secret=keys[1]['api_secret']
)
ws = inverse_perpetual.WebSocket(
    test=False,
    api_key=keys[1]['api_key'],
    api_secret=keys[1]['api_secret']
)


s3_resource = boto3.resource('s3',
        aws_access_key_id=config.AWS_ACCESS_KEY_ID,
        aws_secret_access_key= config.AWS_SECRET_ACCESS_KEY)


print('SESSION', session)

app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['DEBUG'] = True
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


@app.route('/')
def home():

    key = 'tradeJournal_' + month + '.json'
    string = "static/" + key

    with open(string, "r") as f:
        jload = json.load(f)


    return render_template('tradingdesk.html', tradeJournal=json.dumps(jload))


'''##### edit trade info #####'''

# side = 'Buy'
# first = None #first entry
# stop = None
# spread = 2
# percent_risk = 0.5
# lev = None
# minutes = 20
# fraction = 0.95


'''IMPORTANT! must be the same as set on account'''

#################################################################

# position = session.my_position(symbol="BTCUSD")['result']['size']
# pnl =  session.get_wallet_balance()['result']['BTC']['realised_pnl']
# cancel =  session.cancel_all_active_orders(symbol="BTCUSD")['ret_msg']
# rate =  json.dumps(session.query_trading_fee_rate(symbol="BTCUSD"))

@app.route('/getData', methods=['POST'])
def getData():
    mode = request.form ['mode']
    side = request.form ['side']
    minutes = request.form ['minutes']
    risk = float(request.form ['risk'])
    first = float(request.form ['first'])
    fraction = float(request.form ['fraction'])
    stop = float(request.form ['stop'])
    leverage = float(request.form ['leverage'])

    print('SIDE: ', side, minutes, risk, fraction, stop, first)

    if mode == 'first':
        price = float(session.latest_information_for_symbol(symbol="BTCUSD")['result'][0]['last_price'])
        return jsonify({'result' : price, 'mode' : mode})
    elif mode == 'leverage':
        print('LEV: ', side, risk, fraction)
        leverage = setLeverage(first, stop, risk, fraction, leverage)
        return jsonify({'result' : leverage, 'mode' : mode})
    elif mode == 'stop':
        price = getHiLow(minutes, side)
        return jsonify({'result' : price, 'mode' : mode})


@app.route('/getOrder', methods=['POST'])
def getOrder():
    mode = request.form ['mode']
    side = request.form ['side']
    first = float(request.form ['first'])
    spread = int(request.form ['spread'])
    fraction = float(request.form ['fraction'])
    stop = float(request.form ['stop'])
    leverage = float(request.form ['leverage'])


    spreadArray = []

    price = float(session.latest_information_for_symbol(symbol="BTCUSD")['result'][0]['last_price'])
    funds = session.get_wallet_balance()['result']['BTC']['equity']

    if first == None or first == 0:
        first = price

    for i in range(0, spread):
        if side == 'Buy':
            spreadArray.append(first - i*0.5)
        else:
            spreadArray.append(first + i*0.5)

    qty = (price * funds * leverage) * fraction
    print('QTY', price, funds, leverage, qty)

    result = None

    for value in spreadArray:
        result = placeOrder(side, value, stop, qty/len(spreadArray))

    return jsonify({'result' : result})


@app.route('/recordTrade', methods=['POST'])
def recordTrade():
    record = request.form ['record']
    imageArray = request.form ['imageArray']
    currentTrade = request.form ['currentTrade']

    print ('put MetaFile')


    key = 'tradeJournal_' + month + '.json'
    string = "static/" + key

    with open(string, "r") as f:
        jload = json.load(f)

    jload[currentTrade] = {}
    jload[currentTrade]['record'] = json.loads(record)
    jload[currentTrade]['imageArray'] = json.loads(imageArray)

    with open(string, 'w') as json_file:
        json.dump(jload, json_file)

    bucket = 'rekt-journal'
    jstring = json.dumps(jload)
    s3_resource.Bucket(bucket).put_object(
        Key=key, Body=jstring)

    print('json put in bucket location', bucket, key)

    return jsonify({'result' : 'trade recorded'})

@app.route('/addImage', methods=['POST'])
def addImage():
    b64data = request.form ['b64data']
    imageArray = request.form ['imageArray']
    currentTrade = request.form ['currentTrade']

    print(imageArray, type(imageArray))
    imageSet = json.loads(imageArray)

    count = len(imageSet) + 1

    S3_LOCATION = 'https://rekt-journal.s3.ap-northeast-1.amazonaws.com/'
    S3_BUCKET_NAME = 'rekt-journal'
    print('PROCESSING IMAGE')
    image = base64.b64decode(b64data)
    filename = month + '/' + str(currentTrade) + '/' + str(count) +'.png'
    imageLink = S3_LOCATION + filename
    s3_resource.Bucket(S3_BUCKET_NAME).put_object(Key=filename, Body=image)

    imageSet[count] = imageLink

    return jsonify({'result' : json.dumps(imageSet)})



def setLeverage(first, stop, risk, fraction, leverage):

    if first == None or first == 0:
        first = float(session.latest_information_for_symbol(symbol="BTCUSD")['result'][0]['last_price'])

    distance = abs(first - stop)

    percent_difference = (distance/first)*100  # as decimal

    lev = round((risk/percent_difference)*fraction, 1)

    print(first, stop, distance, percent_difference, lev)

    if risk == 0:
        lev = leverage

    if lev < 1:
        print('Leverage too low', lev)
    else:
        print(session.set_leverage(symbol="BTCUSD", leverage=lev))

    return lev

def getHiLow(minutes, side):

    from datetime import datetime
    now = datetime.now()
    timestamp = int(datetime.timestamp(now)) - int(minutes)*60

    data = session.query_kline(symbol="BTCUSD", interval="1", from_time=str(timestamp))['result']

    print('GET HI LOW ', len(data))


    hAry = []
    lAry = []

    for i in range(0, len(data)):

        hAry.append(int(data[i]['high'].split('.')[0]))
        lAry.append(int(data[i]['low'].split('.')[0]))

    mHi = max(hAry)
    mLow = min(lAry)

    print(mLow)

    if side == 'Buy':
        return mLow
    else:
        return mHi

def placeOrder(side, price, stop_loss, qty):

    order = session.place_active_order(
    symbol="BTCUSD",
    side=side,
    order_type='Limit',
    price=price,
    stop_loss = stop_loss,
    take_profit = None,
    qty=qty,
    time_in_force="GoodTillCancel"
    )


    message = order['ret_msg']
    data = json.dumps(order['result'])

    print('ORDER', order)
    print('MESSAGE', message)
    print('DATA', data)

    return data

def shareImage(b64data, log, count, month):

    S3_LOCATION = 'https://rekt-journal-lms.s3.ap-northeast-1.amazonaws.com/'
    S3_BUCKET_NAME = 'rekt-journal'
    print('PROCESSING IMAGE')
    image = base64.b64decode(b64data)
    filename = month + '/' + str(log) + '/' + str(count) +'.png'
    imageLink = S3_LOCATION + filename
    s3_resource.Bucket(S3_BUCKET_NAME).put_object(Key=filename, Body=image)
    return imageLink

def putJson(data, log, month):
    print ('put MetaFile')


    key = 'tradeJournal_' + month + '.json'
    string = "static/" + key

    with open(string, "r") as f:
        jload = json.load(f)

    jload[log] = json.load(data)

    bucket = 'rekt-journal'
    jstring = json.dumps(jload)
    s3_resource.Bucket(bucket).put_object(
        Key=key, Body=jstring)

    print('json put in bucket location', bucket, key)

    return 'ok'

if __name__ == '__main__':
    app.run()