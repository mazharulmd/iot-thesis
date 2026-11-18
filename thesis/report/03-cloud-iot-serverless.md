# Cloud IoT and serverless computing

This chapter introduces the technologies on which the framework is built: the Internet of Things and its messaging protocols, the AWS IoT services, serverless and event-driven computing, and infrastructure as code. The last section describes recent changes in the AWS IoT portfolio that affect any design built on it.

## Internet of Things and MQTT

The Internet of Things (IoT) refers to physical objects that are equipped with sensors, actuators and network connectivity, so that they can report their state and be controlled remotely. A typical IoT architecture has three layers: devices that sense and act, gateways or networks that connect them, and a platform that stores, analyses and acts on the data. (Atzori, Iera & Morabito 2010.) In industrial settings, many sensors are often connected to a local controller, and a gateway aggregates their readings into periodic messages for the platform. This pattern is also used in the simulated data hall of this thesis, where each zone of the hall has one gateway.

MQTT is the most widely used messaging protocol for IoT. It is a lightweight publish–subscribe protocol: devices publish messages to named topics on a broker, and any client subscribed to a topic receives them. Publishers and subscribers do not need to know about each other, which makes the protocol well suited to systems in which devices come and go. MQTT supports three levels of delivery assurance (quality of service), retained messages and persistent sessions, and it runs over TCP, usually protected with TLS. (OASIS 2014.)

## AWS IoT Core

AWS IoT Core is the managed MQTT broker and device platform of Amazon Web Services. Each device is registered as a *thing* and authenticates with its own X.509 certificate. An IoT policy attached to the certificate defines which topics the device may publish and subscribe to, so that a compromised device can only affect its own data. (Amazon Web Services n.d.j.)

Two features of IoT Core are central to this thesis. The first is the *rules engine*. A rule selects messages from topics with an SQL-like statement and forwards them to other AWS services, for example writing them into a DynamoDB table or invoking a Lambda function. Rules make it possible to process telemetry without running any server. (Amazon Web Services n.d.g.)

The second feature is the *device shadow*. A shadow is a JSON document stored in the cloud for each thing, with a *desired* section written by applications and a *reported* section written by the device. When the two differ, IoT Core sends the difference, the *delta*, to the device, which applies it and reports its new state. Because the shadow is stored, a command written while a device is offline is delivered when the device reconnects. (Amazon Web Services n.d.d.) Shadows therefore suit remediation commands well: they are durable, auditable and idempotent, since writing the same desired state twice produces no new delta.

## Serverless and event-driven computing

Serverless computing is a cloud execution model in which the provider manages servers, scaling and availability, and the user supplies only code and configuration. In its most common form, Function as a Service (FaaS), a function runs in response to an event and is billed for its execution time only. Jonas et al. (2019) describe serverless computing as the next phase of cloud computing because it removes the operational work of provisioning and scaling, while noting limitations such as limited execution time, the lack of local state between invocations and the delay of a *cold start* when a new function instance is created. Baldini et al. (2017) reach similar conclusions and highlight that serverless functions are a natural fit for event-driven, short-running tasks.

These properties make serverless computing attractive for IoT. A systematic review of 60 studies concludes that serverless computing is a promising model for IoT applications on the edge, fog and cloud layers, although tooling, latency and state management still need improvement (Cassel et al. 2021). Experimental studies show that cold starts can add noticeable latency when functions are invoked rarely, while warm functions respond quickly (Benedetti et al. 2021). For facility monitoring, where telemetry arrives every few seconds and corrective actions are rare, a pay-per-use model means that the system costs almost nothing when there is no fault.

On AWS, the serverless building blocks used in this thesis are the following:

- **AWS Lambda** runs functions in response to events, scaling automatically with the number of concurrent events (Amazon Web Services n.d.k).
- **Amazon EventBridge** is an event bus that routes events to targets based on rules that match the event content (Amazon Web Services n.d.i).
- **AWS Step Functions** coordinates multi-step workflows defined as state machines. Its Standard workflows can run for up to a year and can pause until an external system returns a *task token*, which makes it possible to wait for a human decision without running any compute in the meantime (Amazon Web Services n.d.l).
- **Amazon DynamoDB** is a serverless key-value and document database. Items can expire automatically through a time-to-live (TTL) attribute, and conditional writes make it possible to implement locks safely (Amazon Web Services n.d.h).
- **Amazon SNS** delivers notifications, for example by email, and **Amazon CloudWatch** collects logs, metrics and alarms.

The combination of these services is an *event-driven architecture*: each message or event triggers the next step, and no component polls for work. Event-driven designs react quickly and scale naturally, but they also make it harder to see the state of the whole system. A recent study notes that serverless systems can fail silently, for example when an invocation is dropped or throttled, and that such failures need their own monitoring (Silent failures in stateless systems 2025). The framework addresses this with an error action that saves failed messages, retries in the workflow, a per-gateway heartbeat record and a monitoring dashboard, described in Chapter 6.

## Infrastructure as code and well-architected design

Infrastructure as code (IaC) means defining infrastructure in version-controlled files instead of configuring it by hand. The same definition can then be deployed repeatedly, reviewed like source code and destroyed when it is no longer needed. (Morris 2020.) The AWS Cloud Development Kit (CDK) lets infrastructure be defined in a general-purpose programming language such as Python, and it synthesises the definitions into AWS CloudFormation templates for deployment (Amazon Web Services n.d.m). Because a whole environment can be created and deleted in minutes, IaC also supports cost control in research projects: the system exists only while experiments run.

The AWS Well-Architected Framework organises good practice into six pillars: operational excellence, security, reliability, performance efficiency, cost optimisation and sustainability (Amazon Web Services n.d.f). The pillars are used in this thesis as a checklist for design decisions, for example per-device certificates and least-privilege roles for security, and dead-letter queues and retries for reliability.

For development and testing, a cloud design can be run against an emulator instead of a real account. LocalStack emulates many AWS services on a local machine, which allows the same infrastructure code to be deployed and tested without cost (LocalStack n.d.). An emulator is not identical to the real service, however, so performance and cost must eventually be measured on AWS itself.

## Changes in the AWS IoT portfolio

AWS has retired several managed IoT services that earlier designs relied on. AWS IoT Analytics reached the end of support on 15 December 2025 (Amazon Web Services n.d.c), AWS IoT Events on 20 May 2026 (Amazon Web Services n.d.e), and Amazon Lookout for Equipment, a managed service for detecting equipment anomalies, ends on 7 October 2026 (Amazon Web Services n.d.a). Amazon Timestream for LiveAnalytics was closed to new customers in 2025 (Amazon Web Services n.d.b). At the same time, AWS IoT SiteWise added built-in multivariate anomaly detection (Amazon Web Services 2025), but it produces alerts rather than corrective actions.

These changes have two consequences for this thesis. First, published reference architectures that combine IoT telemetry with managed analytics services can no longer be followed as such, which motivates a design built only on core services that are actively supported: IoT Core, Lambda, EventBridge, Step Functions and DynamoDB. Second, keeping the anomaly detection inside the framework's own Lambda function, instead of in a managed service, makes the design less dependent on any single service's lifecycle.
