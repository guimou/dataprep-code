## Create Listening KNative service to log events to console
oc create -f service-event-display.yaml

## Create KafkaSource listener to hook to service
oc create -f kafkasource.yaml 

## Monitor events
kubectl logs -l serving.knative.dev/service=logevents -c user-container -n event-display -f