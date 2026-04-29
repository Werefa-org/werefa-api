# 

Adama Science and Technology University   
School of Electrical Engineering and Computing   
Department of Computer Science and Engineering   
Senior Project

# 

# **Werefa: A Real-Time Hybrid Queue Management System and Service Marketplace for SMEs in Ethiopia** {#werefa:-a-real-time-hybrid-queue-management-system-and-service-marketplace-for-smes-in-ethiopia}

|              Name |             ID  |
| :---: | :---: |
| **Abdulwahid Hussen** |           UGR/25287/14 |
| **Ifnan Faysel** |          UGR/26050/14 |
| **Nanati Asamnew** |          UGR/25330/14 |
| **Feysel Abdella** |          UGR/25435/14 |
| **Fasil Hawultie** |          UGR/25578/14 |

# 

# 

# **DECLARATION** {#declaration}

We are students of Adama Science and Technology University in the School of Electrical Engineering and Computing in the Department of Computer Science and Engineering. The information found in this project is our original work. And all sources of materials that will be used for the project work will be fully acknowledged.

| NO | Name | ID | Signature |
| :---- | :---- | :---- | :---- |
| 1 | Nanati Asamnew |  UGR/25330/14 | \_\_\_\_\_\_\_\_\_\_ |
| 2 | Abdulwahid Hussen |  UGR/25287/14 | \_\_\_\_\_\_\_\_\_\_ |
| 3 | Fasil Hawultie |  UGR/25578/14 | \_\_\_\_\_\_\_\_\_\_ |
| 4 | Ifnan Feysal |  UGR/26050/14 | \_\_\_\_\_\_\_\_\_\_ |
| 5 | Feysel Abdella |  UGR/25435/14 | \_\_\_\_\_\_\_\_\_\_ |

**Date of Submission:** June 1, 2026

This project has been submitted for examination with our approval as a university advisor.

**Advisor Name:** Megersa Abetu  
**Signature:** \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Table of Contents**

[**Werefa: A Real-Time Hybrid Queue Management System and Service Marketplace for SMEs in Ethiopia	1**](#werefa:-a-real-time-hybrid-queue-management-system-and-service-marketplace-for-smes-in-ethiopia)

[**DECLARATION	2**](#declaration)

[**ACRONYMS	6**](#acronyms)

[**ACKNOWLEDGEMENT	7**](#acknowledgement)

[**ABSTRACT	8**](#abstract)

[**Chapter 1	9**](#chapter-1)

[**Introduction	9**](#introduction)

[1.1. Introduction	9](#1.1.-introduction)

[1.2. Background of the Project	9](#1.2.-background-of-the-project)

[1.3. Statement of the Problem	10](#1.3.-statement-of-the-problem)

[1.3. Statement of the Problem	10](#1.3.-statement-of-the-problem-1)

[1.4. Objective of the Project	11](#1.4.-objective-of-the-project)

[1.4.1. General Objectives	11](#1.4.1.-general-objectives)

[1.4.2. Specific Objectives	11](#1.4.2.-specific-objectives)

[1.5. Scope and Limitation	12](#1.5.-scope-and-limitation)

[1.5.1. Scope of the Project	12](#1.5.1.-scope-of-the-project)

[1.5.2. Limitations of the Project	12](#1.5.2.-limitations-of-the-project)

[1.6. Deliverables	13](#1.6.-deliverables)

[1.7. Feasibility Study	13](#1.7.-feasibility-study)

[1.7.1. Technical Feasibility	13](#1.7.1.-technical-feasibility)

[1.7.2. Operational Feasibility	13](#1.7.2.-operational-feasibility)

[1.7.3. Economic Feasibility	13](#1.7.3.-economic-feasibility)

[1.8. Significance of the Project	14](#1.8.-significance-of-the-project)

[1.9. Beneficiaries of the project	14](#1.9.-beneficiaries-of-the-project)

[1.10. Methodology	14](#1.10.-methodology)

[1.11. Development Tools	15](#1.11.-development-tools)

[1.12. Required Resources with Cost	16](#1.12.-required-resources-with-cost)

[1.13. Task and Schedule	16](#1.13.-task-and-schedule)

[1.14. Team Composition	16](#1.14.-team-composition)

[**Chapter 2	18**](#chapter-2)

[**Description of Existing System and Literature Review	18**](#description-of-existing-system-and-literature-review)

[2.1. Major Function of Existing System	18](#2.1.-major-function-of-existing-system)

[2.2. Users of Current System	18](#2.2.-users-of-current-system)

[2.3. Drawback of Current System	19](#2.3.-drawback-of-current-system)

[2.4. Literature Review	20](#2.4.-literature-review)

[2.4.1. Theoretical Framework: Queuing Theory	20](#2.4.1.-theoretical-framework:-queuing-theory)

[Relevance to the Project	21](#relevance-to-the-project)

[2.4.2. Review of Global Electronic Queue Management Systems (EQMS)	21](#2.4.2.-review-of-global-electronic-queue-management-systems-\(eqms\))

[2.4.3. Review of Local Solutions in Ethiopia	21](#2.4.3.-review-of-local-solutions-in-ethiopia)

[2.4.4. The Research Gap	22](#2.4.4.-the-research-gap)

[**Chapter 3	23**](#chapter-3)

[**Proposed System	23**](#proposed-system)

[3.1. Overview	23](#3.1.-overview)

[3.2. Functional Requirement	23](#3.2.-functional-requirement)

[3.3. Non-functional Requirement	25](#3.3.-non-functional-requirement)

[3.4. System Model	25](#3.4.-system-model)

[3.4.1. Scenario: Hybrid Queue Synchronization	25](#heading=h.y8n8png03tyc)

[3.4.2. Use Case Model	27](#3.4.2.-use-case-model)

[3.4.2.1. Identification of Actors	27](#3.4.2.2.-identification-of-actors)

[3.4.2.2 Use Case Identification and Description	29](#3.4.2.3-use-case-identification-and-description)

[3.5. Object Model	44](#3.5.-object-model)

[3.5.1. Data Dictionary	44](#3.5.1.-data-dictionary)

[3.5.2. Class Diagram	51](#3.5.2.-class-diagram)

[3.5.3. Dynamic Model	52](#3.5.3.-dynamic-model)

[3.5.4. Sequence Diagrams	52](#3.5.4.-sequence-diagrams)

[3.5.5. Activity Diagrams	57](#3.5.5.-activity-diagrams)

[The Self-Healing Queue	59](#heading=h.ui6yz9ezp3f0)

[3.5.6. State Chart Diagrams	62](#3.5.6.-state-chart-diagrams)

[**Chapter 4	67**](#chapter-4)

[**System Design	67**](#system-design)

[4.1. Overview	67](#4.1.-overview)

[4.2. Purpose of the System Design	67](#4.2.-purpose-of-the-system-design)

[4.3. Design Goals	67](#4.3.-design-goals)

[4.4. Proposed System Architecture	68](#4.4.-proposed-system-architecture)

[Proposed System Architecture Layers & Components	68](#heading=h.t59ks1y6gem5)

[Fig: Proposed System Architecture	71](#heading=h.umd66y4rcq16)

[4.5. Subsystem Decomposition	72](#4.5.-subsystem-decomposition)

[Subsystem Decomposition	72](#heading=h.fd7ubifw5hu)

[4.7. Persistent Data Management	76](#4.7.-persistent-data-management)

[4.7.1 Database Selection Rationale	76](#4.7.1-database-selection-rationale)

[4.7.2 Object-Relational Mapping (ORM) Rules	77](#4.7.2-object-relational-mapping-\(orm\)-rules)

[4.7.3 Normalization & Integrity	78](#4.7.3-normalization-&-integrity)

[Class-to-Database Mapping	79](#heading=h.6uss1smnbhnp)

[4.8. Component Diagram	80](#4.8.-component-diagram)

[4.9. Database Diagram	82](#4.9.-database-diagram)

[4.10. Deployment Diagram	83](#4.10.-deployment-diagram)

[4.11. Access Control	84](#4.11.-access-control)

[**Chapter 5:	87**](#chapter-5:)

[**Implementation	87**](#implementation)

[5.1. Overview	87](#5.1.-overview)

[5.2. Coding Standards	87](#5.2.-coding-standards)

[5.2.1. Naming Conventions	87](#5.2.1.-naming-conventions)

[5.2.2. Directory Structure & Modularity	88](#5.2.2.-directory-structure-&-modularity)

[5.2.3. Error Handling Standards	88](#5.2.3.-error-handling-standards)

[5.2.4. Version Control Guidelines	89](#5.2.4.-version-control-guidelines)

[5.3. Development Tools	89](#5.3.-development-tools)

[5.5. Implementation Detail	95](#5.5.-implementation-detail)

[5.5.1. Client-Side Implementation	95](#5.5.1.-client-side-implementation)

[5.5.2. Server-Side Implementation	96](#5.5.2.-server-side-implementation)

[5.5.3. Algorithmic Prediction Logic	96](#5.5.3.-algorithmic-prediction-logic)

# 

# 

# **List of Tables**

**List of Figures**

| Figure 1 : Agile Methodology | ... |
| :---- | ----: |
| Figure 2 : Use Case Diagram | ... |
| Figure 3 : Class Diagram | ... |
| Figure 4 : Remote Queue Joining | ... |
| Figure 5 : “Call Next” Sequence | ... |
| Figure 6 : Hybrid Walk-In Registration | ... |
| Figure 7 : Automated Liveness check | ... |
| Figure 8 : "Lost Demand" Insights | ... |
| Figure 9 : Smart Join | ... |
| Figure 10 : Provider Service Cycle | ... |
| Figure 11 : The Self-Healing Queue | ... |
| Figure 12 : The Hybrid Engine | ... |
| Figure 13 : Algorithm Self Correction | ... |
| Figure 14 : Queue Ticket Lifecycle | ... |
| Figure 15 : User Reputation Lifecycle | ... |
| Figure 16 : Geolocation Monitoring | ... |
| Figure 17 : Provider Operation | ... |
| Figure 18 : WebSocket Connection | ... |
| Figure 19 : Queue Congestion Controller | ... |
|  Figure 20: Proposed System Architecture | ... |
| Figure 21 :Werefa  Subsystem Decomposition | ... |
| Figure 22 : Class-to-Database Mapping | ... |
| FigureFigure 23 : Werefa System Decomposition | ... |
| Figure 24 : Database Diagram | ... |
| Figure 25 : Deployment Diagram | ... |
| Figure 26 : Dashboard | ... |
| Figure 27 : Services | ... |
| Figure 28 : Search | ... |
| Figure 29 : Queue | ... |

# **ACRONYMS** {#acronyms}

* **API**: Application Programming Interface  
* **BYOD**: Bring Your Own Device  
* **EWT**: Estimated Wait Time  
* **FIFO**: First-In, First-Out  
* **GPS**: Global Positioning System  
* **JWT**: JSON Web Token  
* **PostGIS**: PostgreSQL Spatial Extension  
* **QMS**: Queue Management System  
* **RBAC**: Role-Based Access Control  
* **SaaS**: Software as a Service  
* **SME**: Small and Medium Enterprise  
* **UML**: Unified Modeling Language  
* **WMA**: Weighted Moving Average

# **ACKNOWLEDGEMENT** {#acknowledgement}

We would like to express our deepest gratitude to our advisor, **Megersa Abetu**, for their continuous guidance, technical insights, and encouragement throughout the development of this project. Their expertise was invaluable in shaping the architectural and algorithmic components of the Werefa system.

We also extend our thanks to the faculty of the School of Electrical Engineering and Computing at Adama Science and Technology University for providing the academic foundation necessary for this work. Finally, we thank our families and peers for their unwavering support during the countless hours of research, design, and coding.

# 

# **ABSTRACT** {#abstract}

In the rapidly growing service economy of Ethiopia, time has emerged as a critical yet mismanaged resource. Traditional physical queuing leads to severe overcrowding and wasted productivity. This project proposes Werefa, a cloud-based Queue Management System and Service Marketplace designed to modernize customer flow. The system utilizes a hybrid architecture that synchronizes remote users via a mobile app and walk-in customers via a provider kiosk into a single First-In, First-Out workflow.

The technical implementation features an adaptive time estimation algorithm based on weighted moving averages and a geofenced presence verification system to remove non-responsive users. Built using Flutter for the mobile interface, React.js for the provider portal, and a Node.js backend with a PostgreSQL database, Werefa aims to transform queuing from a passive activity into a data-driven process. The solution enhances operational efficiency for SMEs and returns time sovereignty to the general public.

# 

# 

# 

# 

# 

# 

# 

# **Chapter 1** {#chapter-1}

# **Introduction** {#introduction}

## **1.1. Introduction** {#1.1.-introduction}

In the rapidly growing service economy of Ethiopia, time has emerged as a critical yet often mismanaged resource. For service-oriented enterprises, ranging from specialist medical clinics and beauty salons to public service offices, the efficiency of customer flow is a primary determinant of revenue generation and customer satisfaction. However, the dominant mechanism for managing this flow remains the traditional physical queue. This "first-come, first-served" model necessitates the physical presence of the customer in a lobby or waiting room to secure a position. This reliance on physical presence results in severe overcrowding, unpredictable wait times, and significant productivity losses for the broader economy.

To address these inefficiencies, this project proposes **"Werefa,"** a comprehensive, real-time Queue Management System (QMS) and Service Marketplace. Unlike rigid appointment systems which often fail due to tardiness, or hardware-heavy token machines which are expensive to deploy, Werefa is a mobile-first platform designed to decouple a customer's physical presence from their position in line. The system utilizes a hybrid architecture that synchronizes remote users (via a mobile app) and walk-in customers (via a provider kiosk) into a single, conflict-free workflow. By leveraging dynamic algorithms for time estimation and providing actionable business insights, Werefa aims to transform queuing from a passive, wasteful activity into an active, data-driven process.

## **1.2. Background of the Project** {#1.2.-background-of-the-project}

The challenge of queue management is pervasive throughout Ethiopia’s urban centers. Small and Medium Enterprises (SMEs), particularly private medical clinics, wellness centers, and government service desks, often operate with limited infrastructure to manage demand. They predominantly rely on manual list-keeping or chaotic physical lines. These methods are inherently prone to human error, social friction regarding "line-cutting," and accusations of favoritism, which degrade the customer experience. While global digital solutions exist, they often fail in the local context due to a lack of support for "hybrid" flows the necessity to handle digital and non-digital users simultaneously and prohibitively high subscription costs.

Furthermore, there is a significant "Data Gap" in the local service sector. Business owners currently operate with operational blindness, lacking visibility into their "Lost Demand" specifically, customers who leave because a line looks too long, or those who attempt to visit during closed hours. Consequently, there is a pressing need for a locally tailored solution that not only manages the queue but also creates a transparent marketplace for services, democratizing access to efficient time management for all citizens.

## **1.3. Statement of the Problem** {#1.3.-statement-of-the-problem}

The challenge of queue management is pervasive throughout Ethiopia’s urban centers. Small and Medium Enterprises (SMEs), particularly private medical clinics, wellness centers, and government service desks, often operate with limited infrastructure to manage demand. They predominantly rely on manual list-keeping or chaotic physical lines. These methods are inherently prone to human error, social friction regarding "line-cutting," and accusations of favoritism, which degrade the customer experience. While global digital solutions exist, they often fail in the local context due to a lack of support for "hybrid" flows the necessity to handle digital and non-digital users simultaneously and prohibitively high subscription costs.

Furthermore, there is a significant "Data Gap" in the local service sector. Business owners currently operate with operational blindness, lacking visibility into their "Lost Demand" specifically, customers who leave because a line looks too long, or those who attempt to visit during closed hours. Consequently, there is a pressing need for a locally tailored solution that not only manages the queue but also creates a transparent marketplace for services, democratizing access to efficient time management for all citizens.

## **1.3. Statement of the Problem** {#1.3.-statement-of-the-problem-1}

The core problem addressed by this project is the systemic inefficiency, opacity, and physical congestion inherent in manual queuing systems within the Ethiopian service sector. This issue represents a functional failure in service delivery that impacts multiple dimensions of the economic ecosystem.

The most immediate manifestation of this problem is the lack of predictability for the consumer. Without real-time visibility into queue status, customers are forced to physically travel to a location just to ascertain wait times, leading to wasted travel hours and significant frustration. This opacity effectively tethers individuals to waiting rooms, preventing them from engaging in productive work or rest while waiting for essential services.

Compounding this issue is the "hybrid gap" in existing technologies. Current market solutions tend to be polarized, catering either exclusively to digital users via apps or exclusively to walk-in users via paper lists. There is a distinct lack of unified systems capable of managing both demographics equitably in a single workflow, which hinders the adoption of digital tools in inclusive environments where smartphone penetration is growing but not universal.

Furthermore, the manual nature of current systems results in a loss of critical operational data. Service providers lack the tools to analyze peak hours, measure service duration accuracy, or track customer turn-away rates. This lack of business intelligence prevents owners from optimizing their staffing levels to meet demand, leading to inefficient resource allocation. Finally, the absence of a verified, transaction-based reputation system creates a market where trust is difficult to establish, making it hard for high-quality providers to distinguish themselves from competitors.

## **1.4. Objective of the Project** {#1.4.-objective-of-the-project}

### **1.4.1. General Objectives** {#1.4.1.-general-objectives}

The primary objective of this project is to design and develop "Werefa," a comprehensive, hybrid Queue Management System (QMS) that digitizes customer flow and optimizes service delivery for service-based enterprises in Ethiopia.

### **1.4.2. Specific Objectives** {#1.4.2.-specific-objectives}

To achieve the general objective, the project will focus on the following measurable goals:

1. **To Engineer a Hybrid FIFO Engine:** Develop a backend logic that seamlessly merges asynchronous requests (Remote App joins) and synchronous events (Walk-in Kiosk entries) into a single, conflict-free First-In-First-Out execution queue.  
2. **To Implement an Adaptive Time Estimation Algorithm:** Create a "Weighted Moving Average" algorithm that dynamically recalibrates *Estimated Wait Times (EWT)* based on real-time service completion rates and specific service types.  
3. **To Develop a Geofenced Presence Verification System:** Implement a "Liveness Check" module utilizing GPS geolocation and user confirmation prompts to identify and remove non-responsive users ("ghosts") before they stall the queue.  
4. **To Build a Provider Intelligence Dashboard:** Design an analytics suite that visualizes hidden demand, specifically tracking "Missed Opportunities" (users attempting to join during closed hours) and "Abandonment Rates" to help owners optimize staffing.  
5. **To Create a Location-Based Discovery Service:** Implement a geospatial search engine allowing users to discover "Public" queues within a specific radius and view real-time load factors.  
6. **To Establish a Verified Reputation System:** Develop a transaction-based rating module where users can only review a service after a completed visit, creating a trust score that providers can leverage for visibility boosting.

## **1.5. Scope and Limitation** {#1.5.-scope-and-limitation}

### **1.5.1. Scope of the Project** {#1.5.1.-scope-of-the-project}

The project focuses on developing a solution specifically for **Service-Based Enterprises**. The primary target domains include Private Clinics (Dermatology, Dental), Beauty & Wellness Centers (Salons, Spas), and Vehicle Services.

Functionally, the scope covers three distinct modules. The **User Module** will facilitate "Near Me" discovery, remote joining, real-time tracking, and post-service rating. The **Provider Module** will handle queue control (Next/Skip/No-Show), a Kiosk Mode for walk-ins, and business profile management. The **System Module** will provide the core infrastructure, including real-time WebSocket synchronization, a notification engine (Push/SMS), and offline-first data storage capabilities. Geographically, the pilot implementation and data collection will be restricted to Adama City.

### **1.5.2. Limitations of the Project** {#1.5.2.-limitations-of-the-project}

Despite the robust design, the project operates within certain constraints. Technically, the system is **Dependent on Connectivity**; while an "Offline Mode" will safeguard local data for the provider, real-time updates for remote users will cease during network blackouts. Operationally, the project assumes **Hardware Availability**, meaning providers must possess at least one smartphone or tablet, as the project does not supply hardware. Finally, the system faces an **Adoption Curve**, as the accuracy of the time estimation algorithm relies on the provider consistently updating the status (Start/Finish) of each service manually.

## **1.6. Deliverables** {#1.6.-deliverables}

Upon completion, the project will deliver the following tangible outputs:

1. **Werefa Mobile Application (APK):** A fully functional Android application for end-users.  
2. **Provider Web/Kiosk Portal:** A responsive web application optimized for tablets/desktops for queue management.  
3. **Backend API Infrastructure:** A deployed, secure REST/WebSocket API handling logic and database connections.  
4. **Algorithm Simulation Data:** A dataset demonstrating the accuracy of the Time Estimation Algorithm under various load scenarios.  
5. **Technical Documentation:** Including Software Requirement Specification (SRS) and API Reference Documentation.  
6. **Final Project Report:** A comprehensive academic report detailing the methodology, algorithms, and test results.

## **1.7. Feasibility Study** {#1.7.-feasibility-study}

### **1.7.1. Technical Feasibility** {#1.7.1.-technical-feasibility}

The project is technically viable as it relies on proven, open-source technologies. The architecture utilizes **Flutter** for cross-platform mobile development, ensuring broad device compatibility. The backend leverages **Node.js** with **Socket.io** for low-latency real-time communication. The team possesses the requisite skills in full-stack development to execute this stack effectively.

### **1.7.2. Operational Feasibility** {#1.7.2.-operational-feasibility}

The system is designed for low-friction adoption via a "Bring Your Own Device" (BYOD) model. Providers only need a smartphone and a QR code sticker to operate the system. This eliminates the need for expensive proprietary hardware installation, ensuring high operational feasibility for small businesses.

### **1.7.3. Economic Feasibility** {#1.7.3.-economic-feasibility}

The project is economically sustainable. The development cost is minimal, restricted primarily to time and internet utility. The proposed business model is a low-overhead SaaS architecture (Cloud Hosting), allowing for a sustainable "Freemium" model where basic queuing is free, ensuring rapid market penetration without significant capital investment.

## **1.8. Significance of the Project** {#1.8.-significance-of-the-project}

The implementation of "Werefa" holds significant value for multiple stakeholders. primarily, it enhances **Operational Efficiency**; by smoothing out demand peaks and filling "dead" hours, businesses can increase their daily throughput. Furthermore, the system promotes **Marketplace Transparency** via the verified rating system, which eliminates fake reviews and incentivizes quality service.

From a social perspective, the project contributes to **Public Health & Safety** by reducing physical crowding in enclosed spaces, which mitigates the transmission of airborne pathogens. Finally, it results in **Customer Empowerment** by returning "Time Sovereignty" to the user, allowing them to utilize waiting time productively rather than passively sitting in a lobby.

## **1.9. Beneficiaries of the project** {#1.9.-beneficiaries-of-the-project}

The primary beneficiaries include **The General Public**, specifically individuals seeking services who benefit from reduced wait times and the convenience of waiting from home. **SME Owners** also benefit significantly, gaining operational control, reduced lobby congestion, and data-driven insights to grow their businesses. Finally, **Public Institutions** managing large student or citizen flows benefit from an orderly, documented, and fair queuing mechanism.

## **1.10. Methodology** {#1.10.-methodology}

The project will follow the **Agile Scrum** methodology. This iterative approach is selected to allow for continuous feedback and refinement of features based on real-world testing. The development lifecycle is structured into five distinct phases.

![][image1]

[F☙ure 1](#figur_agile) : Agile Methodology

1. **Phase 1: Analysis:** This phase involves stakeholder interviews with local clinic and salon owners to finalize functional requirements.  
2. **Phase 2: Design:** This involves creating System Models (UML), Database Schema designs, and UI/UX Prototyping.  
3. **Phase 3: Development:** This phase consists of iterative coding sprints (2-week cycles) to build the API, User App, and Provider Portal.  
4. **Phase 4: Testing:** This includes Unit testing, load testing, and User Acceptance Testing (UAT).  
5. **Phase 5: Deployment:** The final phase involves cloud deployment and pilot user onboarding.

## **1.11. Development Tools** {#1.11.-development-tools}

* **Frontend:** Flutter (Mobile), React.js (Web/Kiosk).  
* **Backend:** Node.js / NestJS.  
* **Real-time Protocol:** WebSockets (Socket.io).  
* **Database:** PostgreSQL (Relational Data).  
* **DevOps:** Docker, GitHub, Render/AWS.

## 

## **1.12. Required Resources with Cost** {#1.12.-required-resources-with-cost}

* **Personnel:** 5 Developers (No direct cost).  
* **Equipment:** Personal Laptops and Mobile Devices (Existing resources).  
* **Infrastructure:** Cloud Hosting (Free Tier \- $0.00).  
* **Miscellaneous:** Internet and Transport (\~2,500 ETB).

## **1.13. Task and Schedule** {#1.13.-task-and-schedule}

The project activities are structured into phased tasks with a defined timeline to ensure systematic development and timely completion.

* **October – November:** Literature Review, Problem Analysis, Requirement Gathering, and Proposal Preparation and Defense.  
* **December – January:** System Architecture Design, Database Schema Design, UML Modeling, and User Interface/User Experience (UI/UX) Prototyping.  
* **February – March:** Core Development Phase, including Backend API development, Mobile Application development, and Provider Web/Kiosk Portal implementation.  
* **April:** System Integration, Functional Testing, Performance Testing, and User Acceptance Testing (UAT).  
* **May:** Pilot Deployment in Adama City, Result Evaluation, Final Documentation, and Project Defense.

## **1.14. Team Composition** {#1.14.-team-composition}

The project is carried out by a team of five members. To ensure efficiency and effective collaboration, responsibilities are distributed as follows:

* **Nanati Asamnew (Project Manager & Documentation Lead):** Responsible for overall project coordination, task scheduling, stakeholder communication, and preparation of proposal, final report, and technical documentation.  
* **Abdulwahid Hussen (System Architect & Backend Developer):** Responsible for designing the system architecture, developing backend APIs, managing the database, and implementing queue management and time estimation algorithms.  
* **Fasil Hawultie (Mobile Application Developer):** Responsible for developing the user-facing Android mobile application using Flutter, implementing geolocation features, notifications, and real-time queue tracking.  
* **Ifnan Feysal (Frontend & Provider Portal Developer):** Responsible for designing and implementing the provider web/kiosk interface using React, focusing on usability, responsiveness, and analytics dashboard visualization.  
* **Feysel Abdella (Quality Assurance & Deployment Engineer):** Responsible for system testing, bug tracking, integration testing, deployment support, and ensuring system reliability and performance.

# 

# 

# 

# **Chapter 2** {#chapter-2}

# **Description of Existing System and Literature Review** {#description-of-existing-system-and-literature-review}

## **2.1. Major Function of Existing System** {#2.1.-major-function-of-existing-system}

The current ecosystem for managing customer flow in the Ethiopian service sector specifically within private clinics, beauty salons, and public service offices is predominantly manual and analog. The existing system operates on a strict **Physical First-Come, First-Served (FCFS)** basis, which relies heavily on human intervention and physical oversight.

The operational workflow of this prevalent system functions through four distinct stages. It begins with the **Registration of Arrival**, where the input mechanism is strictly tied to physical presence. A customer must physically travel to the service location and either verbally report to a receptionist or manually inscribe their name on a paper roster to secure a position. Following registration, the system performs **Sequential Allocation**, assigning ordinal numbers (1, 2, 3...) based exclusively on the chronological order of arrival. While some large institutions, such as commercial banks, have introduced semi-automated hardware ticket dispensers, these devices simply print a static number and do not digitize the workflow.

Once registered, the customer enters the **Physical Waiting** phase. The primary service provided by the system during this phase is simply "holding the spot," which necessitates that the stakeholder remains within earshot or visual range of the service provider. This effectively tethers the customer to the waiting room, preventing them from engaging in other productive activities. The cycle concludes with **Service Initiation**, where the provider manually calls out the name or number corresponding to the head of the line, initiating the service delivery.

## **2.2. Users of Current System** {#2.2.-users-of-current-system}

The stakeholders of the current manual queuing system can be categorized into two distinct groups, each facing specific challenges due to the system's limitations.

1\. Service Seekers (Customers)

This group comprises individuals seeking essential services, ranging from medical care and grooming to administrative documentation. These users are typically time-constrained and value efficiency. Their primary expectation is fairness specifically, the assurance that no latecomers will "cut the line" and predictability regarding when they will be served. However, the current reality forces them to trade productive time for a place in line. They often suffer from anxiety regarding "missing their turn" if they step out for food or work, and they endure significant physical discomfort in overcrowded and often poorly ventilated waiting areas.

2\. Service Providers (SMEs)

This group includes business owners and frontline staff (receptionists) responsible for managing customer intake. Their objective is to maximize throughput and maintain an orderly lobby environment. However, under the current system, they spend a disproportionate amount of time mediating disputes over queue positions and managing impatient crowds. Furthermore, they operate with "Operational Blindness." Because paper lists do not capture timestamped data on service duration or abandonment, providers lack the necessary insights to analyze peak hours or understand how many potential customers walked away due to long lines.

## **2.3. Drawback of Current System** {#2.3.-drawback-of-current-system}

The existing manual and hardware-token systems exhibit critical limitations that hinder operational efficiency, compromise public health, and degrade the customer experience.

Requirement of Physical Presence (The "Tethering" Problem)

The most significant drawback is the requirement of physical presence. This constraint forces 100% of the waiting time to be "unproductive time" spent sitting in a lobby, rather than "productive time" spent at work or home. This tethering effect creates a barrier to entry for busy professionals who cannot afford undefined waiting periods.

Lack of Time Predictability

Manual systems provide only ordinal data (e.g., "You are 5th in line") but fail to provide temporal data (e.g., "You will be served in 45 minutes"). Without dynamic estimation that accounts for the specific service type such as the difference between a simple haircut and a complex treatment customers cannot effectively plan their day, leading to perceived wait times that are often longer than reality.

Inability to Handle Hybrid Flows

Current solutions are binary: either everyone walks in (manual list) or everyone books days in advance (rigid appointment books). There is no existing mechanism to seamlessly merge a digital request with a physical walk-in. This lack of hybrid capability creates friction when businesses attempt to modernize, as they fear alienating their non-digital customers.

Operational Opacity and Health Risks

From a business perspective, paper lists generate no analytics. Owners cannot query a notebook to analyze average service speeds or staff performance, preventing data-driven decision-making. Furthermore, the physical concentration of people in small waiting rooms poses legitimate health risks, increasing the likelihood of airborne disease transmission in clinics and public offices.

## **2.4. Literature Review** {#2.4.-literature-review}

This section reviews relevant theoretical frameworks and existing technological solutions to contextualize the Werefa project within the broader academic and industrial landscape.

### **2.4.1. Theoretical Framework: Queuing Theory** {#2.4.1.-theoretical-framework:-queuing-theory}

This project is grounded in **Queuing Theory**, the mathematical study of waiting lines and service systems. One of the central principles applied in this system is **Little’s Law**, which states:

**L \= λ × W**

Where:

* **L** \= the average number of customers in the system

* **λ (lambda)** \= the average effective arrival rate

* **W** \= the average time a customer spends in the system

Little’s Law explains that, in a stable system, the long-term average number of customers is equal to the arrival rate multiplied by the average waiting time.

#### **Relevance to the Project** {#relevance-to-the-project}

Current manual queue management systems in Ethiopia do not effectively control either the **arrival rate (λ)** or the **waiting time (W)**. This results in physical overcrowding, long queues, and inefficient service delivery.

The **Werefa** system applies queuing theory principles by *smoothing the effective arrival rate*. Users are allowed to enter a **virtual queue** rather than physically crowding service facilities. As a result, the number of people in the system (**L**) is managed digitally, decoupling queue length from physical congestion. This optimizes service flow and reduces waiting times without requiring additional physical infrastructure.

### **2.4.2. Review of Global Electronic Queue Management Systems (EQMS)** {#2.4.2.-review-of-global-electronic-queue-management-systems-(eqms)}

On a global scale, solutions such as **Queue-it** (virtual waiting rooms for high-traffic websites) and **Yelp Waitlist** (for restaurant seating) have successfully digitized the queuing process. These platforms allow for remote check-ins and utilize SMS notifications to keep users informed.

**Limitations in Local Context:** However, these systems are often vertical-specific, tailored heavily towards dining or e-commerce. They lack the "Service-Specific Logic" required for Ethiopian SMEs, such as salons or clinics, where service times vary wildly based on the procedure type. Furthermore, reliance on credit card payment gateways and continuous high-speed internet infrastructures renders many global SaaS tools unsuitable for the local Ethiopian market.

### **2.4.3. Review of Local Solutions in Ethiopia** {#2.4.3.-review-of-local-solutions-in-ethiopia}

Technological intervention in the Ethiopian queuing landscape has been largely limited to the banking and telecom sectors.

* **Hardware Token Dispensers:** Institutions like the Commercial Bank of Ethiopia utilize kiosk machines that print paper tickets. While this organizes the physical crowd, it remains a "blind" system; it does not allow remote joining, nor does it provide real-time updates to the user once they leave the immediate area.  
* **Appointment-Based Apps:** Several "Doctor Booking" applications have attempted to enter the market. However, these are fundamentally *Scheduling* systems for future dates, not *Queuing* systems for immediate service. Given the local culture of immediate consumption and walk-in service, rigid appointment systems often face high non-compliance rates and are ill-suited for high-volume, random-arrival businesses.

### **2.4.4. The Research Gap** {#2.4.4.-the-research-gap}

The review of literature and existing systems reveals a distinct gap: there is a lack of **Hybrid, Mobile-First Queuing Solutions** tailored specifically for the Ethiopian service sector. Existing global solutions are too rigid or expensive, while local hardware solutions are incapable of remote interaction. Currently, no system exists that combines **Dynamic Time Estimation** (based on service type), **Hybrid Entry** (Walk-in \+ Remote), and **Marketplace Discovery** into a single platform for SMEs. **Werefa** aims to bridge this specific gap by providing a locally relevant, algorithm-driven solution.

# **Chapter 3** {#chapter-3}

# **Proposed System** {#proposed-system}

## **3.1. Overview** {#3.1.-overview}

The Werefa system is a hybrid, cloud-based Queue Management System (QMS) and Service Marketplace designed to modernize the service economy in Ethiopia. Its primary objective is to decouple a customer’s physical presence from their position in a queue, thereby eliminating the "tethering" problem associated with traditional physical lines. The architecture is built on a mobile-first philosophy, utilizing a cross-platform application for users to discover services and join queues remotely. Simultaneously, it provides a specialized web-portal for service providers (clinics, salons, government desks) that includes a "Kiosk Mode" to manage walk-in customers. By merging these two distinct streams into a single, synchronized FIFO (First-In-First-Out) engine, Werefa ensures equity and transparency for both digital and non-digital users.

## **3.2. Functional Requirement** {#3.2.-functional-requirement}

The functional requirements define the specific behaviors and operations the "Werefa" system must execute to meet the operational needs of Service Seekers and Providers.

[Table 1](#table_fr) : Functional Requirements

| ID | Category | Requirement Name | Description |
| :---- | :---- | :---- | :---- |
| **FR-01** | Core Operations | Service-Specific Queuing | Allow users to select specific Service Packages; assign estimated duration based on service type rather than a generic average. |
| **FR-02** | Core Operations | Multi-Channel Entry | Support remote queue entry via mobile app and instant "Walk-In" registration via physical QR Code (Deep Link). |
| **FR-03** | Core Operations | Unified Queue Sequence | Merge "Remote Users" and "Walk-In Users" into a single, conflict-free FIFO (First-In-First-Out) list. |
| **FR-04** | Geospatial Logic | Provider Geofencing | Allow providers to set a "Maximum Join Radius" (e.g., 500m); block users outside this radius from joining. |
| **FR-05** | Geospatial Logic | Liveness Verification | Perform background GPS checks when a user reaches "Top 3"; flag potential "No-Shows" if the user isn't moving toward the location. |
| **FR-06** | Time & Notification | Dynamic EWT | Calculate wait times using a Service-Weighted Moving Average to prevent long services from inflating short service wait times. |
| **FR-07** | Time & Notification | Smart Pre-Alerts | Trigger "Head to Counter" notifications based on a combination of queue position and user travel time. |
| **FR-08** | Time & Notification | Mass Broadcasting | Enable providers to send manual broadcast messages to all waiting users for status updates or emergencies. |
| **FR-09** | Provider Control | Queue Flow Management | Provide controls for: "Call Next," "Recall," "Mark No-Show," and "Pause Queue" (stop new entries). |
| **FR-10** | Provider Control | Service Management | Allow providers to Create, Edit, and Delete service types, including "Baseline Duration" and "Price" settings. |
| **FR-11** | Integrity & Post-Service | Verified Review System | Restrict the "Rate & Review" feature until a ticket status is marked "Completed" by the provider. |
| **FR-12** | Integrity & Post-Service | No-Show Penalty Logic | Track no-shows and temporarily block remote queue access if a user exceeds a configurable threshold (e.g., 3 misses/month). |

## 

## **3.3. Non-functional Requirement** {#3.3.-non-functional-requirement}

The non-functional requirements specify the quality attributes and constraints of the Werefa system:

[Table 2](#table_nfr) : Non Functional Requirement

| ID | Attribute | Requirement Name | Description |
| :---- | :---- | :---- | :---- |
| **NFR-01** | Performance | Low Latency | Synchronize queue state updates across all devices in \< 2 seconds using WebSocket protocols. |
| **NFR-02** | Reliability | Offline Resilience | Provider kiosks must use local caching to allow walk-in registration and management during internet outages. |
| **NFR-03** | Scalability | System Capacity | Backend must handle at least 1,000 concurrent queue join requests per city without performance degradation. |
| **NFR-04** | Security | Data Protection | All user data (phone numbers, location) must be encrypted at rest and in transit via TLS/SSL. |
| **NFR-05** | Availability | System Uptime | Maintain a minimum uptime of 99.5% for the service marketplace. |
| **NFR-06** | Usability | Low-Friction UX | The provider interface must require minimal data entry to move the queue forward. |
| **NFR-07** | Compatibility | Cross-Platform | The application must function on both low-end and high-end Android and iOS devices. |

## **3.4. System Model** {#3.4.-system-model}

The system model for Werefa is founded on a distributed, three-tier architecture designed to bridge the digital-physical divide in the Ethiopian service sector. This model integrates three distinct layers: the **Client Layer** (comprising the user mobile app and provider kiosk), the **Communication Layer** (utilizing real-time WebSocket protocols), and the **Core Logic Layer** (the centralized FIFO and Time Estimation engines). The conceptual framework of this model is "Hybrid Synchronization," where the system treats asynchronous remote requests and synchronous physical walk-ins as equal data entities. By maintaining a single, cloud-hosted source of truth, the system ensures that the queue state is consistent across all interfaces, effectively transforming a chaotic physical environment into a structured, data-driven workflow.

### **3.4.1. Scenarios**

To demonstrate the system's comprehensive capability to manage complex, multi-actor workflows, three primary operational scenarios are defined. These narratives illustrate the "End-to-End" flow for the Service Seeker, the Service Provider, and the System Administrator, ensuring all functional requirements are contextualized within real-world applications.

#### **Scenario A: The Hybrid Service Loop (Discovery & Synchronization)**

*This scenario illustrates the "Happy Path" of the system, focusing on the core innovation: merging remote digital requests with physical walk-in traffic.*

The workflow initiates when a Service Seeker ("Chala") accesses the mobile application to locate a dental service. Utilizing the **Search & Discovery Module (UC-01)**, Chala filters providers by "Shortest Wait Time." Unlike traditional static listings, the system requires Chala to select a specific **Service Package** (e.g., "Root Canal Treatment"). The **Time Estimation Engine** queries the active queue specifically for that service type and calculates a dynamic Estimated Wait Time (EWT) of 45 minutes, filtering out shorter procedures like simple checkups to ensure accuracy.

Upon executing the **"Remote Join" (UC-02)** command, the system triggers a geospatial validation routine. The **Geofence Module (UC-03)** compares Chala's GPS coordinates against the Provider’s configured Maximum Join Radius (5km). Once validated, the system generates digital token **\#A-09** and establishes a persistent WebSocket connection for real-time telemetry.

While Chala waits remotely, a "Walk-In" customer ("Sara") arrives physically at the clinic without a smartphone. The Service Provider utilizes the **Kiosk Interface** to register Sara manually **(UC-04)**. The **Hybrid FIFO Engine** instantly ingests this manual entry, assigning Sara the next sequential token (**\#A-10**). Crucially, the system immediately triggers a "Global State Update" via the WebSocket layer. Chala’s device is instantly updated to reflect the new queue density, ensuring that the remote EWT remains accurate despite the physical arrival. This demonstrates the system's ability to act as a **Single Source of Truth** for disparate input channels.

#### **Scenario B: Exception Handling & Real-Time Control**

*This scenario demonstrates the system's resilience in handling operational deviations, such as delays, missing customers, and emergency communication.*

During the service cycle, the Provider encounters an unexpected equipment issue requiring a 15-minute halt. To prevent queue saturation, the Provider toggles the **"Pause Queue" (UC-13)** switch. The system immediately disables the "Join" button for all prospective remote users while maintaining the positions of those already in line. Simultaneously, the Provider utilizes the **"Broadcast Alert" (UC-11)** function to push a mass notification—*"Doctor is on emergency break"*—to all active tokens. Chala receives this notification instantly as a high-priority alert, managing his expectations and reducing "Wait Anxiety."

As operations resume and Chala advances to the "Top 3" position, the system executes a background **Liveness Check (UC-03)**. It verifies that Chala’s GPS coordinates are converging toward the facility. If the system had detected Chala was stationary or moving away, it would have flagged the entry for potential skipping. However, Chala arrives on time.

The Provider clicks **"Call Next" (UC-05)**, changing Chala’s status to "Serving." If Chala had failed to appear, the Provider would have utilized the **"Mark No-Show" (UC-06)** function, which logs a penalty strike against Chala’s profile and instantly advances the queue to Sara (\#A-10). Upon service completion, the **Reputation Module (UC-08)** unlocks the review interface on Chala’s app, allowing him to verify the wait-time accuracy and close the transaction loop.

#### **Scenario C: Business Lifecycle & Optimization**

*This scenario focuses on the B2B administrative workflow, detailing how providers are verified, configured, and optimized using data.*

The ecosystem grows when a new Service Provider ("Dr. Abebe") registers his clinic. His account is initially set to a "Pending" state. The **System Administrator** accesses the Admin Console to execute **Credential Verification (UC-10)**. After reviewing Dr. Abebe's uploaded Business License and cross-referencing it with the trade registry, the Admin marks the account as "Verified," unlocking the public profile.

Dr. Abebe then logs in to configure his **Service Menu (UC-09)**. He defines three distinct services: "Consultation" (15 mins), "Cleaning" (30 mins), and "Surgery" (60 mins). He also sets a **Geofence Radius (UC-14)** of 3km to prevent overcrowding from distant users. This configuration is critical, as it primes the algorithm to differentiate wait times based on patient intent and location.

At the end of the week, Dr. Abebe accesses the **Demand Analytics Module (UC-07)**. He reviews a heat map showing that he missed 15 potential customers (Lost Demand) during the lunch hour—users who viewed the profile but abandoned the queue due to the "Paused" status. Using this data, he decides to adjust his staffing schedule to keep the queue open during lunch, thereby optimizing his revenue and throughput.

#### **Scenario D: The Connectivity Failure Protocol (Resilience & Offline Logic)**

*This scenario addresses the critical non-functional requirement of "Offline Resilience" (NFR-02), demonstrating how the system handles the common reality of intermittent internet connectivity in the local context.*

During peak operating hours, the "Adama Dental" clinic experiences a sudden ISP outage, severing the connection between the Provider Kiosk and the Cloud Server. A new walk-in patient ("Dawit") arrives during this downtime. Instead of halting operations, the Kiosk Interface automatically switches to **"Offline Mode."** The receptionist registers Dawit normally; the application stores the transaction data locally in the browser’s persistent storage (IndexedDB) and assigns a temporary, locally-hashed ticket number.

Simultaneously, the remote mobile application for users like Chala detects the server timeout. To prevent frustration, it displays a **"Last Known State"** cached timestamp, informing Chala that the displayed position (\#3) is an estimate. Once the clinic's internet connection is restored (e.g., via 4G backup), the Kiosk’s **Synchronization Engine** automatically pushes the pending local record (Dawit) to the cloud. The Central FIFO Engine resolves the conflict, officially slotting Dawit into position \#11, and broadcasts a unified state update to all connected devices, ensuring zero data loss during the outage.

#### **Scenario E: Administrative Oversight & Governance**

*This scenario details the "Super Admin" workflows (UC-15, UC-16) required to maintain platform security, health, and user compliance.*

The **System Administrator** begins the shift by monitoring the **System Health Dashboard (UC-15)**. A real-time alert triggers indicating "High Latency" in the Bole Sub-city region due to an unexpected surge in traffic. The Admin scales the WebSocket server resources to handle the load.

While reviewing the daily **Audit Logs**, the Admin flags an anomaly: a specific user account ("User X") has accumulated 5 "No-Show" penalties across three different providers in a single week. This violates the platform’s "Fair Usage Policy." Acting on this intelligence, the Admin executes the **"Manage User Accounts" (UC-16)** protocol. The Admin issues a temporary "Account Suspension," effectively banning User X from joining any new queues for 30 days. This action preserves the integrity of the ecosystem and protects providers from abusive booking behavior.

#### **Scenario F: The "Low-Friction" Guest Experience**

*This scenario focuses on Accessibility (UC-12), illustrating how the system captures users who do not have the full mobile application installed, thereby lowering the barrier to entry.*

A potential customer ("Hana") walks past a new beauty salon and notices a "Werefa" placard. Hana does not have the Werefa app installed and is reluctant to download a 50MB file just to check the wait time. She scans the **Physical QR Code (UC-12)** using her standard camera app.

Instead of forcing a store download, the system resolves the Deep Link to a lightweight **Progressive Web App (PWA)**. This "Instant App" interface loads immediately, displaying the salon’s current wait time (15 mins) and service menu. Hana selects "Manicure" and joins the queue as a "Guest User" verified via a simple SMS OTP. This seamless entry proves the system’s **"Mobile-First, App-Optional"** philosophy, successfully capturing transient foot traffic that would otherwise be lost due to digital friction.

### **3.4.2. Use Case Model** {#3.4.2.-use-case-model}

The Use Case Model details the functional requirements of the Werefa" system by capturing the interactions between external actors and the system itself. This model serves as a contract between the stakeholders and the technical team, ensuring that every user goal—from joining a queue to analyzing business performance is explicitly defined.

### **3.4.2.1 User Stories**

This section outlines the functional requirements from the perspective of the end-users. Each story follows the standard "As a... I want to... So that..." format to capture the specific value proposition and includes detailed acceptance criteria to guide the implementation.

#### **A. Core System User Stories**

**User Story ID:** US-SYS-00 (Maps to UC-00) 

**Title:** Secure Authentication & Authorization 

**Priority:** Critical 

**User Story:** As a **Registered User (Seeker, Provider, or Admin)**, I want to securely log in to the system using my phone number and a one-time password (OTP) or password, so that my personal data, queue history, and administrative privileges remain protected from unauthorized access. 

**Acceptance Criteria:**

* Must validate the phone number format before sending an OTP.  
* Must lock the account temporarily after 5 failed login attempts to prevent brute-force attacks.  
* Must issue a secure JSON Web Token (JWT) upon successful verification.  
* Must route the user to the correct dashboard (Seeker, Provider, or Admin) based on their assigned role. 

**Dependencies:** None

#### **B. Service Seeker User Stories**

**User Story ID:** US-SS-01 (Maps to UC-01) 

**Title:** Search and Discovery of Providers 

**Priority:** High 

**User Story:** As a **Service Seeker**, I want to search for service providers based on my current geolocation, specific categories (e.g., Clinics, Banks), or business names, and filter these results by current wait times, so that I can make an informed decision about where to go to save the most time. 

**Acceptance Criteria:**

* Must request GPS permissions and identify the user's current coordinates.  
* Must display a list of providers sorted by default distance (nearest first).  
* Must show the real-time "Estimated Wait Time" (EWT) on the search result card.  
* Must allow filtering results by rating (e.g., "4 Stars & Up") and Category. 

**Dependencies:** US-SYS-00

**User Story ID:** US-SS-02 (Maps to UC-02) 

**Title:** Remote Queue Joining 

**Priority:** Critical

 **User Story:** As a **Service Seeker**, I want to join a provider's digital queue remotely from my mobile device after selecting a specific service type, so that I can secure my position in line without needing to physically travel to the location immediately. 

**Acceptance Criteria:**

* Must require the user to select a specific **Service Package** (e.g., "Standard Haircut").  
* Must calculate the initial EWT using the algorithm specific to that service type.  
* Must successfully generate a digital ticket number (e.g., A-09) if the join is successful.  
* Must prevent the user from joining if they are already active in another queue. 

**Dependencies:** US-SS-01, US-SP-14

**User Story ID:** US-SS-03 (Maps to UC-03) 

**Title:** Geofenced Presence Verification 

**Priority:** High 

**User Story:** As a **Service Seeker**, I need the system to verify my GPS location when I attempt to join a queue or when I reach the front of the line, so that I am not unfairly blocked by "ghost users" who are too far away to actually receive the service. 

**Acceptance Criteria:**

* Must calculate the Haversine distance between the User and the Provider.  
* Must compare this distance against the Provider’s configured **Maximum Join Radius**.  
* Must reject the "Join Queue" request if the distance exceeds the allowed limit.  
* Must trigger a background "Liveness Check" when the user moves to position \#3.

 **Dependencies:** US-SS-02

**User Story ID:** US-SS-08 (Maps to UC-08) 

**Title:** Verified Transactional Review 

**Priority:** Medium 

**User Story:** As a **Service Seeker**, I want to submit a rating and textual review only after my service has been officially completed, so that I can provide authentic feedback on the service quality and the accuracy of the wait-time estimation. **Acceptance Criteria:**

* Must be disabled/locked until the ticket status is updated to "Completed".  
* Must allow a 1-5 Star rating and optional text comment.  
* Must include a mandatory boolean question: "Was the time estimate accurate?"  
* Must immediately recalculate the Provider's average rating upon submission. 

**Dependencies:** US-SP-05

**User Story ID:** US-SS-12 (Maps to UC-12) 

**Title:** Scan QR / Deep Link Join 

**Priority:** High

 **User Story:** As a **Service Seeker**, I want to scan a physical QR code posted at the provider's entrance to instantly join the queue, so that I can skip the search process and register myself even if I am a "Walk-In" user with a smartphone. 

**Acceptance Criteria:**

* Must recognize the specific Werefa URL pattern from the QR code.  
* Must launch the app and navigate directly to the specific Provider’s "Join" screen.  
* Must bypass the standard GPS check if the QR code is static and trusted (optional) or validate GPS to ensure the code wasn't shared remotely.  
* Must tag the source of the queue entry as "QR\_Scan" for analytics. 

**Dependencies:** US-SYS-00

#### **C. Service Provider User Stories**

**User Story ID:** US-SP-04 (Maps to UC-04) 

**Title:** Hybrid Walk-In Registration

 **Priority:** Critical 

**User Story:** As a **Service Provider**, I want to manually register customers who arrive physically without a smartphone via my Kiosk dashboard, so that they are fairly integrated into the same queue as the remote users. 

**Acceptance Criteria:**

* Must allow the input of an optional Guest Name or Phone Number.  
* Must require the selection of a Service Type to ensure accurate time estimation.  
* Must assign the next sequential ticket number to the walk-in user.  
* Must update the wait time for all subsequent remote users instantly. 

**Dependencies:** US-SP-09

**User Story ID:** US-SP-05 (Maps to UC-05) 

**Title:** Call Next Customer 

**Priority:** Critical 

**User Story:** As a **Service Provider**, I want to call the next customer in the queue with a single click, so that the system automatically notifies them and updates the public display without me needing to shout names. 

**Acceptance Criteria:**

* Must visually highlight the ticket at the top of the FIFO list.  
* Must change the ticket status from "Waiting" to "Serving" upon clicking.  
* Must send a Push Notification ("Now Serving Ticket \#...") to the user's device.  
* Must start a background timer to track the service duration. 

**Dependencies:** US-SS-02

**User Story ID:** US-SP-06 (Maps to UC-06) 

**Title:** Mark No-Show / Skip **Priority:** Medium 

**User Story:** As a **Service Provider**, I want to mark a customer as a "No-Show" if they fail to appear after being called, so that the queue continues moving and the system can penalize repeat offenders. **Acceptance Criteria:**

* Must provide a "Mark No-Show" button only after a ticket has been called.  
* Must remove the ticket from the active service screen.  
* Must log a "Strike" against the user's profile in the database.  
* Must prompt the provider to immediately call the next available ticket. 

**Dependencies:** US-SP-05

**User Story ID:** US-SP-07 (Maps to UC-07) 

**Title:** View Demand Analytics

 **Priority:** Medium

**User Story:** As a **Service Provider**, I want to view detailed charts regarding my peak hours, average service times, and lost demand, so that I can make data-driven decisions about staffing and operating hours. 

**Acceptance Criteria:**

* Must display a "Peak Hours" heat map (Time of Day vs. Volume).  
* Must show "Average Service Duration" calculated from actual completed tickets.  
* Must allow filtering data by Day, Week, and Month.  
* Must export the data summary to CSV or PDF format. 

**Dependencies:** US-SP-05

**User Story ID:** US-SP-09 (Maps to UC-09) 

**Title:** Configure Service Packages 

**Priority:** High **User Story:** As a **Service Provider**, I want to define the list of services I offer and assign a baseline duration to each, so that the system's algorithm has a starting point for calculating accurate wait times for different customer needs. 

**Acceptance Criteria:**

* Must allow adding a Service Name (e.g., "Consultation") and Duration (e.g., 20 mins).  
* Must allow editing or deleting existing services (unless active tickets exist).  
* Must allow setting a visible price for the service. 

**Dependencies:** US-SYS-00

**User Story ID:** US-SP-11 (Maps to UC-11) 

**Title:** Broadcast Manual Queue Alert 

**Priority:** Low 

**User Story:** As a **Service Provider**, I want to send a custom mass message to all currently waiting users, so that I can instantly communicate emergency delays, lunch breaks, or technical issues without calling each person individually.

 **Acceptance Criteria:**

* Must provide a text input field for the custom message.  
* Must allow selection of "Pre-set" messages (e.g., "Doctor is 15 mins late").  
* Must dispatch the notification only to users with status "Waiting".  
* Must log the broadcast event in the system history. 

**Dependencies:** US-SP-05

**User Story ID:** US-SP-13 (Maps to UC-13) 

**Title:** Pause / Resume Queue 

**Priority:** Medium 

**User Story:** As a **Service Provider**, I want to temporarily toggle my queue status to "Paused," so that I can stop new users from joining while I finish serving the current batch, without marking the business as completely closed. 

**Acceptance Criteria:**

* Must provide a visible "Pause Queue" toggle on the dashboard.  
* Must disable the "Join" button on the User App immediately.  
* Must show a "Resuming Shortly" banner to public users.  
* Must NOT cancel or remove existing tickets in the queue. 

**Dependencies:** US-SYS-00

**User Story ID:** US-SP-14 (Maps to UC-14) 

**Title:** Configure Geofence Radius 

**Priority:** Medium 

**User Story:** As a **Service Provider**, I want to adjust the maximum physical radius from which users are allowed to join my queue, so that I can control the flow of customers and ensure they are close enough to arrive on time. 

**Acceptance Criteria:**

* Must provide a slider input (e.g., 500m to 10km).  
* Must visualize the radius on a map interface during setup.  
* Must save the new radius value to the Provider Profile.  
* Must enforce the new radius on all future API join requests. 

**Dependencies:** US-SYS-00

#### **D. System Administrator User Stories**

**User Story ID:** US-AD-10 (Maps to UC-10) 

**Title:** Verify Business Credentials 

**Priority:** High

 **User Story:** As a **System Administrator**, I want to review and verify the documents submitted by new Service Providers, so that I can maintain the platform's integrity and prevent fraudulent businesses from listing services. 

**Acceptance Criteria:**

* Must list all providers with "Pending" status.  
* Must allow viewing/downloading the uploaded Business License.  
* Must provide "Approve" (Activate) and "Reject" (Deactivate) actions.  
* Must require a comment/reason when rejecting an application. 

**Dependencies:** US-SYS-00

**User Story ID:** US-AD-15 (Maps to UC-15) 

**Title:** Monitor System Health 

**Priority:** Medium **User Story:** As a **System Administrator**, I want to view a real-time dashboard of server performance, error rates, and active user counts, so that I can detect and resolve technical outages before they affect the user experience. 

**Acceptance Criteria:**

* Must show CPU and Memory usage of the backend server.  
* Must display the count of currently connected WebSocket clients.  
* Must list recent Critical Error logs from the application. 

**Dependencies:** US-SYS-00

**User Story ID:** US-AD-16 (Maps to UC-16) 

**Title:** Manage User Accounts 

**Priority:** Low 

**User Story:** As a **System Administrator**, I want to ban abusive users or reset passwords for providers who have lost access, so that I can manage the user base and handle escalated support tickets.

 **Acceptance Criteria:**

* Must allow searching for users by Phone Number or Name.  
* Must display the user's "No-Show" history and Reputation score.  
* Must allow "Ban/Unban" actions with a confirmation dialog.  
* Must allow "Force Password Reset" which sends a temp PIN to the user. 

**Dependencies:** US-SYS-00

#### **3.4.2.2. Identification of Actors** {#3.4.2.2.-identification-of-actors}

The system identifies three primary actors who interact with the platform. Each actor represents a specific user role with defined permissions and responsibilities.

[Table 3](#table_ss) : Service Seeker Actor Identification

| Name | Service Seeker |
| :---- | :---- |
| **Description** | The Service Seeker is the end-user or customer who accesses the system via the mobile application to find and join service queues remotely. |
| **Responsibilities** | • Search and discover nearby service providers. • Join public queues remotely or private queues via QR code. • Track real-time estimated wait times (EWT) and position. • Perform "Liveness Checks" to confirm attendance. • Submit ratings and reviews after service completion. |

[Table 4](#table_ss2) : Service Provider Actor Identification

| Name |  | Service Provider |
| :---- | :---- | :---- |
| **Description** |  | The Service Provider is the business owner or front-desk staff (e.g., clinic receptionist, salon manager) who operates the Kiosk/Web portal to manage the customer flow. |
| **Responsibilities** |  | • Configure business profile and service duration settings. • Register walk-in customers into the digital queue (Hybrid Entry). • Manage queue operations (Call Next, Skip, Park, Mark No-Show). • View "Lost Demand" analytics and operational dashboards. • Manage queue visibility (Public/Private) and promotion (Boost). |

[Table 5](#table_sa) : Service Administrator Actor Identification

| Name | System Administrator (Admin) |
| :---- | :---- |
| **Description** | The Admin is a high-level user with platform-wide privileges, responsible for the maintenance, security, and verification of the Werefa ecosystem. |
| **Responsibilities** | • Verify and approve new Service Provider accounts (KYC). • Monitor overall system health and server performance. • Manage user accounts and handle escalated support issues. • Oversee platform-wide analytics and reporting. |

#### **3.4.2.3 Use Case Identification and Description** {#3.4.2.3-use-case-identification-and-description}

[Table 6](#table_uc1) : Search & Filter Providers (UC-01)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **Search & Filter Providers** |
| **Use-case ID** | **UC-01** |
| **Actor** | Service Seeker |
| **Description** | Users search for service providers based on location, category, or name and filter results by wait time or rating. |
| **Pre-Conditions** | 1\. The user has installed the mobile application. 2\. GPS/Location services are enabled on the device. |
| **Main Flow** | 1\. User launches the application. 2\. System requests access to geolocation services. 3\. System retrieves the user’s current coordinates. 4\. System displays a list of providers sorted by proximity. 5\. User enters a keyword (e.g., "Dental") or selects a category icon. 6\. System filters the list and displays providers matching the criteria. 7\. User applies a filter (e.g., "Shortest Wait Time"). 8\. System updates the list view based on the selected filter. |
| **Alternative Flows** | **3a. GPS Denied:** If the user denies GPS permission, the system prompts the user to manually select a city/sub-city. **7a. Clear Filters:** User taps "Clear All." System reverts to the default proximity-based list. |
| **Exception Flows** | **E1. Network Failure:** If the internet connection is lost, the system displays "Offline \- Cannot load providers" and offers a retry button. **E2. No Results:** If no providers match the search criteria, the system displays "No service providers found in this area." |
| **Post-Conditions** | The user is presented with a curated list of providers containing real-time wait data. |

[Table 7](#table_uc2) : Join Virtual Queue (UC-02)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **Join Virtual Queue** |
| **Use-case ID** | **UC-02** |
| **Actor** | Service Seeker |
| **Description** | A remote user joins a service queue after location and intent verification. |
| **Pre-Conditions** | 1\. User is logged in. 2\. The target Service Provider is currently "Open" and "Accepting Joins." |
| **Main Flow** | 1\. User selects a specific provider from the search results. 2\. User selects a specific **Service Package** (e.g., Haircut vs. Shave). 3\. System calculates EWT based on the service type and current load. 4\. User taps the "Join Queue" button. 5\. System triggers **Verify Presence via GPS (UC-03)**. 6\. Upon success, System generates a unique digital ticket (e.g., A-09). 7\. System updates the user’s dashboard with the ticket number and live position. |
| **Alternative Flows** | **4a. Cancel Join:** User taps "Cancel" on the confirmation modal. The system returns to the provider profile. **6a. Queue Full:** If the provider has reached max capacity, the system suggests trying again later. |
| **Exception Flows** | **E1. Geofence Violation:** If UC-03 fails (user is too far), system displays an error: "You are outside the join radius." **E2. Duplicate Entry:** If the user is already in another queue, system displays: "You cannot join multiple queues simultaneously." |
| **Post-Conditions** | A new QueueEntry is created in the database, and the provider’s EWT is updated for subsequent users. |

[Table 8](#table_uc3) :  Verify Presence via GPS (UC-03)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **Verify Presence via GPS** |
| **Use-case ID** | **UC-03** |
| **Actor** | System (Background Process) |
| **Description** | Confirms that the user is physically within an acceptable distance to prevent queue abuse. |
| **Pre-Conditions** | User attempts to join a queue OR reaches the top 3 position in line. |
| **Main Flow** | 1\. System requests high-accuracy GPS coordinates from the user's device. 2\. System retrieves the Provider’s configured **Geofence Radius**. 3\. System calculates the Haversine distance between the User and Provider. 4\. If Distance ≤ Radius, the system returns a "Success" flag. 5\. If Distance \> Radius, the system returns a "Failure" flag. |
| **Alternative Flows** | None (System Logic). |
| **Exception Flows** | **E1. GPS Signal Lost:** If coordinates cannot be retrieved within 10 seconds, the system prompts the user to move to an open area and retry. **E2. Location Spoofing:** If the system detects mock location software, the request is immediately rejected with a security warning. |
| **Post-Conditions** | The user's presence status is verified (Pass/Fail). |

[Table 9](#table_uc4) :  Register / Manage Walk-ins (UC-04)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **Register / Manage Walk-ins** |
| **Use-case ID** | **UC-04** |
| **Actor** | Service Provider |
| **Description** | Provider manually registers an in-person customer into the digital queue. |
| **Pre-Conditions** | Provider is logged into the Kiosk or Web Dashboard. |
| **Main Flow** | 1\. Walk-in customer arrives at the service desk. 2\. Provider clicks "Add Walk-in Customer." 3\. Provider enters optional details (Name/Phone) or leaves as "Guest." 4\. Provider selects the requested Service Type. 5\. System inserts the customer into the unified FIFO queue. 6\. System prints a physical ticket (if printer connected) or displays the number on screen. |
| **Alternative Flows** | **3a. Repeat Customer:** Provider enters a phone number, and system auto-fills the name from history. |
| **Exception Flows** | **E1. Offline Mode:** If internet is down, the system stores the entry locally and syncs it once the connection is restored. **E2. Queue Paused:** If the queue is paused, the system asks for confirmation to override the pause for a walk-in. |
| **Post-Conditions** | The walk-in customer holds a valid queue position, and remote users' EWT is adjusted. |

[Table 10](#table_uc5) :  Call Next Customer (UC-05)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **Call Next Customer** |
| **Use-case ID** | **UC-05** |
| **Actor** | Service Provider |
| **Description** | Provider calls the next customer in the queue for service. |
| **Pre-Conditions** | The queue contains at least one ticket with status "Waiting." |
| **Main Flow** | 1\. Provider views the Dashboard showing the queue list. 2\. Provider clicks the "Call Next" button. 3\. System identifies the ticket at the head of the line. 4\. System updates ticket status to "Serving." 5\. System triggers a Push Notification ("Now Serving Ticket \#...") to the user. 6\. System starts the Service Timer. |
| **Alternative Flows** | **2a. Specific Call:** Provider selects a specific ticket (not the head) to call out of order (e.g., for an emergency). |
| **Exception Flows** | **E1. Notification Failure:** If the push notification fails, the system logs a warning but proceeds with the status change. |
| **Post-Conditions** | The customer is marked as "In Service," and the queue moves forward by one position. |

[Table 11](#table_uc6) : Mark No-Show / Skip (UC-06)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **Mark No-Show / Skip** |
| **Use-case ID** | **UC-06** |
| **Actor** | Service Provider |
| **Description** | Handles customers who do not appear when called. |
| **Pre-Conditions** | A customer has been in "Serving" status (called) but is not physically present. |
| **Main Flow** | 1\. Provider calls the customer and waits for the defined grace period. 2\. Customer does not appear. 3\. Provider clicks "Mark No-Show." 4\. System removes the ticket from the active screen. 5\. System increments the "No-Show Count" on the user's profile. 6\. System prompts Provider to call the next ticket. |
| **Alternative Flows** | **3a. Park Customer:** Instead of No-Show, Provider selects "Park/Hold." The ticket is moved to a "Holding" list to be recalled later. |
| **Exception Flows** | **E1. Action Timeout:** If the provider leaves a ticket in "Serving" for \>2 hours, system auto-flags it for review. |
| **Post-Conditions** | The ticket is finalized as "No-Show," and the user's reputation score is decremented. |

[Table 12](#table_uc7) : View Demand Analytics (UC-07)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **View Demand Analytics** |
| **Use-case ID** | **UC-07** |
| **Actor** | Service Provider |
| **Description** | Displays insights on customer demand and missed opportunities. |
| **Pre-Conditions** | Sufficient historical data exists in the database. |
| **Main Flow** | 1\. Provider navigates to the "Insights" tab. 2\. System aggregates data for "Peak Hours," "Avg Wait Time," and "Lost Demand." 3\. System renders interactive charts. 4\. Provider selects a date range (e.g., Last 7 Days). 5\. Charts update to reflect the selected period. |
| **Alternative Flows** | **4a. Export Data:** Provider clicks "Export CSV" to download raw data for external analysis. |
| **Exception Flows** | **E1. No Data:** If the account is new, system displays "Insufficient data to generate reports." |
| **Post-Conditions** | Provider has access to visual performance metrics. |

[Table 13](#table_uc8) : Submit Transactional Review (UC-08)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **Submit Transactional Review** |
| **Use-case ID** | **UC-08** |
| **Actor** | Service Seeker |
| **Description** | User provides feedback on service quality and wait-time accuracy. |
| **Pre-Conditions** | The ticket status must be "Completed" by the provider. |
| **Main Flow** | 1\. User receives a "Service Completed" notification. 2\. App displays the Rating Modal. 3\. User selects a Star Rating (1-5). 4\. User toggles "Was the time estimate accurate?" (Yes/No). 5\. User adds an optional text comment. 6\. User clicks "Submit." 7\. System saves the review and updates the Provider’s average score. |
| **Alternative Flows** | **2a. Skip Review:** User dismisses the modal. The review remains pending in their history. |
| **Exception Flows** | **E1. Submission Error:** If the network fails during submit, system caches the review to retry later. |
| **Post-Conditions** | A validated review is linked to the completed transaction. |

[Table 14](#table_uc9) : Configure Service Durations (UC-09)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **Configure Service Durations** |
| **Use-case ID** | **UC-09** |
| **Actor** | Service Provider |
| **Description** | Allows providers to define average service durations for accurate EWT calculation. |
| **Pre-Conditions** | Provider is logged in with Admin/Manager privileges. |
| **Main Flow** | 1\. Provider navigates to "Service Menu." 2\. Provider clicks "Add New Service." 3\. Provider inputs Name (e.g., "Consultation") and Baseline Duration (e.g., 20 mins). 4\. Provider inputs Price (optional). 5\. Provider saves the service. 6\. System updates the available options for Service Seekers. |
| **Alternative Flows** | **2a. Edit Service:** Provider selects an existing service to update its price or duration. **2b. Delete Service:** Provider removes a service that is no longer offered. |
| **Exception Flows** | **E1. Active Ticket Conflict:** If provider tries to delete a service currently in use by a waiting customer, system blocks the action. |
| **Post-Conditions** | The service catalog is updated, influencing future EWT calculations. |

[Table 15](#table_uc10) : Verify Business Credentials (UC-10)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **Verify Business Credentials** |
| **Use-case ID** | **UC-10** |
| **Actor** | System Administrator |
| **Description** | Admin verifies the legitimacy of service providers before public listing. |
| **Pre-Conditions** | A new Provider has completed registration and uploaded KYC documents. |
| **Main Flow** | 1\. Admin logs into the Admin Console. 2\. Admin views the "Pending Verifications" queue. 3\. Admin selects a provider and reviews the uploaded Business License. 4\. Admin validates the license number against the trade registry. 5\. Admin clicks "Approve." 6\. System activates the Provider’s account and sends a welcome email. |
| **Alternative Flows** | **5a. Reject Application:** Admin clicks "Reject" and provides a reason (e.g., "Blurry Document"). System notifies the provider to re-upload. |
| **Exception Flows** | **E1. Corrupt File:** If the uploaded document cannot be opened, Admin requests a re-upload. |
| **Post-Conditions** | The Provider is either "Verified" (Visible to public) or "Rejected" (Hidden). |

[Table 16](#table_uc11) : Broadcast Queue Alert (UC-11)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **Broadcast Queue Alert** |
| **Use-case ID** | **UC-11** |
| **Actor** | Service Provider |
| **Description** | The provider sends a custom mass notification to all currently waiting users. |
| **Pre-Conditions** | There is at least one user with status "Waiting" in the queue. |
| **Main Flow** | 1\. Provider clicks the "Broadcast Alert" button. 2\. Provider selects a reason (e.g., "Emergency Break") or types a custom message. 3\. Provider confirms the broadcast. 4\. System identifies all active device tokens for the queue. 5\. System dispatches a high-priority push notification. 6\. App displays the message as a sticky banner on the user’s screen. |
| **Alternative Flows** | **2a. Cancel:** Provider cancels the action before sending. |
| **Exception Flows** | **E1. Zero Users:** If the queue is empty, system displays "No active users to notify." |
| **Post-Conditions** | All waiting users are informed of the operational update. |

[Table 17](#table_uc12) : Scan QR / Deep Link Join (UC-12)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **Scan QR / Deep Link Join** |
| **Use-case ID** | **UC-12** |
| **Actor** | Service Seeker |
| **Description** | A user joins a queue instantly by scanning a physical QR code. |
| **Pre-Conditions** | User is physically present at the provider location. |
| **Main Flow** | 1\. User opens camera or app scanner. 2\. User scans the printed "Werefa QR Code." 3\. System resolves the Deep Link and launches the specific Provider Page. 4\. User selects a service and clicks "Confirm." 5\. System registers the entry with source tag "QR\_Scan." 6\. User receives a digital ticket. |
| **Alternative Flows** | **3a. Web Fallback:** If the app is not installed, the QR opens a lightweight Web App (PWA) to allow guest joining. |
| **Exception Flows** | **E1. Invalid QR:** If the code is damaged or not a Werefa code, system displays "Invalid Code." |
| **Post-Conditions** | User is added to the queue without needing to search or filter manually. |

[Table 18](#table_uc13) : Pause / Resume Queue (UC-13)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **Pause / Resume Queue** |
| **Use-case ID** | **UC-13** |
| **Actor** | Service Provider |
| **Description** | The provider temporarily stops new users from joining the queue. |
| **Pre-Conditions** | The business is currently Open. |
| **Main Flow** | 1\. Provider toggles the "Accepting Joins" switch to OFF. 2\. System asks for confirmation. 3\. System updates the public profile status to "Paused." 4\. The "Join Queue" button becomes disabled for all Service Seekers. 5\. Existing users in the queue retain their spots. |
| **Alternative Flows** | **1a. Resume:** Provider toggles the switch back to ON. The public profile returns to "Open." |
| **Exception Flows** | **E1. Sync Lag:** If network is slow, system shows a loading spinner until the state is confirmed on the server. |
| **Post-Conditions** | No new queue entries can be created until the queue is resumed. |

[Table 19](#table_uc14) : Configure Geofence Radius (UC-14)

| Field | Description |
| :---- | :---- |
| **Use-case Name** | **Configure Geofence Radius** |
| **Use-case ID** | **UC-14** |
| **Actor** | Service Provider |
| **Description** | The provider defines the maximum physical distance allowed for joining. |
| **Pre-Conditions** | Provider is logged in. |
| **Main Flow** | 1\. The provider goes to "Location Settings." 2\. The system displays a map with the current radius overlay. 3\. The provider drags the slider (e.g., 500m to 5km). 4\. The system visually updates the circle on the map. 5\. The provider clicks "Save." 6\. System updates the parameter in the database. |
| **Alternative Flows** | **3a. Unlimited Mode:** Provider selects "No Limit" (disabling geofence entirely). |
| **Exception Flows** | **E1. Invalid Range:** If provider tries to set a radius \<10 meters, system warns "Radius too small." |
| **Post-Conditions** | Future join requests are validated against the new distance threshold. |

**3.4.2.3. Use case Diagram**

![][image2]

[F☙ure 2](#figur_usecase) : Use Case Diagram

## **3.5. Object Model** {#3.5.-object-model}

The object model defines the static and dynamic structures of the data entities within the system.

### **3.5.1. Data Dictionary** {#3.5.1.-data-dictionary}

The following elements represent the core data structures:

[Table 20](#table_datadict): Data Dictionary

| Class | Attribute | Type / Constraint | Description |
| :---- | :---- | :---- | :---- |
| **User** | userId | UUID (PK) | Unique identifier for the service seeker. |
|  | fullName | Varchar(100) | Full legal name of the user. |
|  | phoneNumber | Varchar(15) | Validated mobile number (used for login/OTP). |
|  | passwordHash | Varchar(255) | Encrypted password string. |
|  | fcmToken | Varchar | device's specific push notification token to send messages like "Now Serving" or "Broadcast Alerts." |
|  | geoLoc | Point (Lat, Long) | Current GPS coordinates for proximity checks. |
|  | reputation | Integer | Score (0–100) used to filter high-risk users. |
|  | noShowCount | Integer | Counter for missed appointments (penalty logic). |
|  | isBanned | Boolean | Flag to block users with excessive no-shows. |
| **Provider** | providerId | UUID (PK) | Unique identifier for the business. |
|  | verificationStatus | Enum: Pending, Verified, Rejected | whether an Admin has approved the business. |
|  | documentUrl | varchar | To store the path to the uploaded business license image for the Admin to review. |
|  | isPaused | Boolean | "Taking a Break" without closing the business entirely. |
|  | bizName | Varchar(100) | Commercial name of the service center. |
|  | qrSlug | varchar | You need a unique string for deep linking. |
|  | isOpen | Boolean | Status flag (True \= Open, False \= Closed). |
|  | geoFence | Float | Radius in meters (e.g., 500m) for allowing queue joins. |
|  | isPrivate | Boolean | If true, queue is hidden from public search. |
|  | accessCode | Varchar(6) | The secret PIN required to join if queue is private. |
|  | boostLevel | Integer | Monetization level (0=None, 1=Basic, 2=Premium). |
|  | boostExpiresAt | DateTime | Timestamp when the paid visibility boost ends. |
| **ServiceItem** | serviceId | UUID (PK) | Unique identifier for a specific service type. |
|  | providerId | UUID (FK) | Links this service to a specific Provider. |
|  | serviceName | Varchar(50) | Name of service (e.g., "Haircut", "Consultation"). |
|  | avgDuration | Integer | Baseline duration in minutes used for algorithm. |
|  | price | Decimal(10,2) | Cost of the service (displayed to user). |
| **QueueEntry** | ticketId | UUID (PK) | Unique identifier for the queue transaction. |
|  | userId | UUID (FK, Nullable) | Link to User (Null if it is a walk-in guest). |
|  | serviceId | UUID (FK) | Link to the specific service chosen. |
|  | ticketNum | Integer | The visual number (e.g., A-004) displayed on screen. |
|  | reminderSent | Boolean | to know if it has already sent the "You are 5 spots away" notification so it doesn't send it again. |
|  | actualDuration | Integer | to store how long *this specific* ticket actually took to update the average later. |
|  | status | Enum | Values: Waiting, Serving, Completed, NoShow, Cancelled. |
|  | source | Enum | Values: RemoteApp or KioskWalkIn. |
|  | guestName | Varchar(50) | Name of the customer (if walk-in). |
|  | estStartTime | DateTime | The algorithm’s predicted time for service start. |
| **DemandLog** | logId | UUID (PK) | Unique identifier for the insight event. |
|  | providerId | UUID (FK) | The provider who “lost” or “gained” this traffic. |
|  | eventType | Enum | Values: ViewedProfile, JoinAttemptClosed, Abandoned. |
|  | timestamp | DateTime | Exact time the event occurred (for peak hour analysis). |
| **Review** | reviewId | UUID (PK) | Unique identifier for the feedback. |
|  | ticketId | UUID (FK) | Links to the completed QueueEntry (verified transaction). |
|  | rating | Integer | 1–5 star rating. |
|  | timeAccurate | Boolean | “Was the estimated time accurate?” (True/False). |
|  | comment | Text | Optional textual feedback from the user. |
| **Admin** | adminId | UUID (PK) | Unique identifier for system administrators. |
|  | role | Enum | Values: SuperAdmin, Moderator. |
|  | lastLogin | DateTime | Audit trail for admin access. |

### 

| NotificationLog | broadcastId | UUID (PK) | Unique ID for a manual broadcast event. |
| :---- | :---- | :---- | :---- |
| (For UC-11) | providerId | UUID (FK) | The provider who sent the alert. |
|  | messageBody | Text | The content sent (e.g., "Doctor is 15 mins late"). |
|  | sentAt | DateTime | When the message was pushed. |
|  | targetCount | Integer | Number of users who received this alert. |
| **AdminActionLog** | logId | UUID (PK) | Unique ID for the audit trail. |
| (For UC-16) | adminId | UUID (FK) | The admin who performed the action. |
|  | actionType | Enum | Values: VerifyProvider, BanUser, ResetPassword. |
|  | targetId | UUID | The ID of the User or Provider who was affected. |
|  | details | Text | Optional notes (e.g., "Banned for abusive language"). |

### 

### 

### 

### 

### 

### 

### 

### 

### 

### **3.5.2. Class Diagram** {#3.5.2.-class-diagram}

The class diagram shows the relationships between the persistent objects in the Werefa database.

![][image3]  
[F☙ure 3](#figur_classdiagram) : Class Diagram

### **3.5.3. Dynamic Model** {#3.5.3.-dynamic-model}

The dynamic model tracks how the system state evolves. When a "Join" event occurs, the system transitions from an **Idle** state to an **Update** state, where it triggers a recalculation of all Estimated Wait Times (EWT) for everyone currently in that specific provider’s list.

### 

### **3.5.4. Sequence Diagrams** {#3.5.4.-sequence-diagrams}

![][image4]

[F☙ure 4](#figur_sequence1) : Remote Queue Joining

**"Call Next" sequence.**  
![][image5]  
[F☙ure 5](#figur_seq2) : “Call Next” Sequence  
![][image6]

[F☙ure 6](#figur_seq3) : Hybrid Walk-In Registration  
![][image7]  
[F☙ure 7](#figur_seq4) : Automated Liveness check  
**"Lost Demand" Insights**

![][image8]

### 

[F☙ure 8](#figur_seq5) : "Lost Demand" Insights

### 

### **3.5.5. Activity Diagrams** {#3.5.5.-activity-diagrams}

**Smart Join**  
![][image9]

[F☙ure 9](#figur_act1) : Smart Join  
**Provider Service Cycle**

![][image10]

### 

[F☙ure 10](#figur_act2) : Provider Service Cycle

### 

### 

**The Self-Healing Queue**  
![][image11]

### 

[F☙ure 11](#figur_act3) : The Self-Healing Queue

**The Hybrid Engine**

**![][image12]**

[F☙ure 12](#figur_act4) : The Hybrid Engine

![][image13]

### 

### 

### 

[F☙ure 13](#figur_act5) : Algorithm Self Correction

### 

### 

### 

### 

### 

### 

### 

### 

### 

### 

### **3.5.6. State Chart Diagrams** {#3.5.6.-state-chart-diagrams}

![][image14]

[F☙ure 14](#figur_state1) : Queue Ticket Lifecycle

# **![][image15]**

[F☙ure 15](#figur_state2) : User Reputation Lifecycle

# **![][image16]**

[F☙ure 16](#figur_state3) : Geolocation Monitoring

# **![][image17]**

[F☙ure 17](#figur_state5) : Provider Operation

# **![][image18]**

[F☙ure 18](#figur_state6) : WebSocket Connection

# **![][image19]**

[F☙ure 19](#figur_state7) : Queue Congestion Controller

# 

# 

# 

# 

# **Chapter 4** {#chapter-4}

# **System Design** {#system-design}

## **4.1. Overview** {#4.1.-overview}

The system design for "Werefa" provides the technical translation of the requirements into a functional software architecture. This phase focuses on the structural organization of the platform, defining how the mobile application, provider portal, and cloud backend interact to solve the problem of physical queue congestion. The design emphasizes a "hybrid" approach, where the system is capable of merging multiple input streams into a single, synchronized data flow. By establishing clear interfaces and modular components, this design ensures that the platform is scalable, reliable, and capable of operating within the infrastructure constraints of urban centers like Adama.

## **4.2. Purpose of the System Design** {#4.2.-purpose-of-the-system-design}

The primary purpose of the system design is to provide a comprehensive technical roadmap that bridges the gap between the initial project concept and the final implementation. It ensures that every functional requirement, such as dynamic time estimation and geospatial discovery, has a dedicated technical solution.

* **Architectural Rationale:** The design justifies the selection of a three-tier architecture to ensure that the core logic is centralized, preventing data conflicts between different users.  
* **Verification and Testing:** It establishes a framework for modular testing, allowing each subsystem to be verified independently before full-scale integration.  
* **Implementation Support:** By defining the database schema and API structures, the design minimizes ambiguity during the coding phase, ensuring that the developers can build the system efficiently.

## **4.3. Design Goals** {#4.3.-design-goals}

The following engineering principles guide the design of Werefa to ensure the system is both robust and flexible:

* **Modularity and High Cohesion:** The system is divided into self-contained modules, such as the "Notification Engine" and the "FIFO Engine," each focusing on a single, specific task.  
* **Low Coupling:** The front-end interfaces (Mobile and Web) are decoupled from the back-end database through an API gateway, allowing for updates to the UI without affecting core logic.  
* **Real-time Responsiveness:** The design prioritizes low-latency updates so that users receive position changes in real-time, which is essential for reducing "wait anxiety."  
* **Data Consistency:** The system must strictly enforce ACID (Atomicity, Consistency, Isolation, Durability) properties to ensure that queue positions are never duplicated or lost.

## **4.4. Proposed System Architecture** {#4.4.-proposed-system-architecture}

Werefa adopts a **Three-Tier Client-Server Architecture** which separates the system into the Presentation, Application, and Data layers. The Presentation layer consists of the Flutter mobile app and the React.js provider portal. The Application layer, built on Node.js and NestJS, contains the business logic, including the algorithms for time estimation and geofence verification. Finally, the Data layer manages persistent storage.

To handle the real-time requirements of a live queue, this architecture is augmented with a **WebSocket Layer**. This allows the server to "push" updates to the clients instantly rather than waiting for the client to request data. This combination of traditional REST APIs for data entry and WebSockets for status updates creates a highly responsive environment.

[Table 21](#table_layers) : Proposed System Architecture Layers & Components

| Layer | Component | Function & Technical Responsibility |
| :---- | :---- | :---- |
| **1\. Client Layer (Presentation)** | **Mobile Application (Flutter / Android)** | **Service Seeker Interface:** • Manages GPS hardware access for location validation. • Establishes a persistent WebSocket connection for live queue updates. • Caches critical data locally for offline resilience. |
|  | **Provider Kiosk Portal (React.js / Web)** | **Management Dashboard:** • Provides a centralized view for Queue Control (Call Next, No-Show). • Visualizes data analytics and charts. • Handles “Walk-In” registration (Hybrid Entry). |
| **2\. Server Layer (Application Logic)** | **API Gateway & Router (Node.js / Express)** | **Traffic Management:** • Acts as the single entry point for all incoming requests. • Routes standard HTTP traffic to controllers and upgrades connections to WebSockets for real-time clients. • Implements rate limiting to prevent DDoS attacks. |
|  | **Authentication Module (Passport.js / JWT)** | **Security & Access Control:** • Generates and validates stateless JSON Web Tokens (JWT). • Enforces Role-Based Access Control (RBAC) to strictly separate Admin, Provider, and Seeker privileges. |
|  | **Queue Engine (Core Logic) (Custom Algorithms)** | **Business Logic:** • Enforces FIFO (First-In-First-Out) integrity. • Handles concurrency locking (ensuring two providers cannot call the same ticket). • Calculates dynamic Estimated Wait Time (EWT) based on service averages. |
|  | **Real-Time Event Hub (Socket.io)** | **Asynchronous Communication:** • Manages rooms and namespaces for specific businesses. • Pushes instant state changes (e.g., “Ticket \#45 is Serving”) to all connected clients without polling. |
| **3\. Data Layer (Persistence)** | **Relational Database (PostgreSQL)** | **Structured Storage:** • Stores persistent records (Users, Tickets, Transaction Logs). • Uses ACID transactions to ensure data consistency during high-concurrency queue operations. |
|  | **Spatial Engine (PostGIS Extension)** | **Geospatial Processing:** • Executes optimized spatial queries (e.g., ST\_DWithin) to validate geofences. • Calculates precise linear distances between Users and Providers efficiently. |

![][image20]

 [F☙ure 20](#figur_system): Proposed System Architecture

## 

## **4.5. Subsystem Decomposition** {#4.5.-subsystem-decomposition}

Subsystem decomposition is a critical architectural process that partitions the complex "Werefa" platform into smaller, manageable, and highly cohesive units. By dividing the system based on functional boundaries, this design ensures that each module handles a specific set of responsibilities while maintaining low coupling with other parts of the architecture. This modular approach not only enhances code maintainability and testability but also facilitates parallel development of distinct features.

The proposed system is decomposed into four primary subsystems: the **Marketplace & Discovery Subsystem** for geospatial search, the **Queue Management Engine** for core serialization logic, the **Notification Service** for real-time alerts, and the **Administrative Analytics Subsystem** for business intelligence. The following table details these subsystems, their internal components, and their specific roles within the integrated platform.

[Table 22](#table_ssd) : Subsystem Decomposition

| Subsystem | Components | Description & Responsibilities |
| :---- | :---- | :---- |
| **1\. Queue Management Subsystem (The Core Logic)** | **Ticket Serializer** | Generates unique, non-colliding ordinal ticket numbers (e.g., A-001, A-002) while enforcing FIFO (First-In-First-Out) integrity. |
|  | **Concurrency Lock Manager** | Implements mutex logic to prevent race conditions (e.g., preventing two providers from calling the same ticket simultaneously). |
|  | **Wait Time Estimator** | Dynamically calculates Estimated Wait Time (EWT) by analyzing the average service duration of the last five completed tickets. |
|  | **State Machine Handler** | Manages ticket lifecycle transitions (Waiting → Called → Serving → Completed / No-Show). |
| **2\. Marketplace & Discovery Subsystem (Geospatial)** | **Geospatial Indexer** | Utilizes PostGIS to execute spatial queries (e.g., ST\_DWithin) for finding providers within a 5 km radius of the user. |
|  | **Provider Search Engine** | Filters businesses based on real-time metadata such as service category, current queue status (Open / Full), and user rating. |
|  | **Distance Calculator** | Computes the linear distance between the user’s GPS coordinates and the provider to assist in travel time estimation. |
| **3\. Real-Time Notification Subsystem (Communication)** | **WebSocket Event Hub** | Manages persistent connections (Socket.io) to push instant updates (e.g., queue position changes) to clients without polling. |
|  | **Alert Dispatcher** | Orchestrates multi-channel notifications, including in-app toasts for active users and system tray push notifications for background users. |
|  | **SMS Gateway Wrapper** | Provides a fallback mechanism to send verification codes (OTP) or critical alerts to users with poor internet connectivity. |
| **4\. Identity & Security Subsystem (Access Control)** | **Auth Controller** | Handles secure user registration and login using JWT (JSON Web Tokens) for stateless authentication. |
|  | **Reputation Manager** | Tracks user behavior (e.g., no-show count) and automatically enforces temporary bans if the three-strikes threshold is exceeded. |
|  | **Role-Based Access Control (RBAC)** | Enforces strict permission boundaries, ensuring service seekers cannot access provider management interfaces. |
| **5\. Analytics & Intelligence Subsystem (Business Insight)** | **Log Aggregator** | Archives historical transaction data (service start and end times) for performance auditing. |
|  | **Metric Calculator** | Computes key performance indicators (KPIs) such as peak traffic hours, average service rate, and customer abandonment rate. |
|  | **Report Visualizer** | Transforms raw data into JSON structures consumable by frontend charting libraries (e.g., daily traffic graphs). |

![][image21]

[F☙ure 21](#figur_subsytem) :Werefa  Subsystem Decomposition

**4.6. Subsystem Description**

This section details the operational responsibilities of the identified subsystems and how they collaborate to fulfill the platform's requirements.

**1\. Queue Management Subsystem** Acting as the central "brain" of the platform, this subsystem handles the complex logic of serialization. It is responsible for the lifecycle of every ticket, from creation to completion. Critical to its function is the **Concurrency Lock Manager**, which ensures that despite hundreds of simultaneous requests, no two users are ever assigned the same ticket number or called by the same provider at the same time.

**2\. Marketplace & Discovery Subsystem** This subsystem serves as the entry point for Service Seekers. It abstracts the complexity of geospatial calculations, allowing users to find "nearest" providers without manual input. By integrating with the queue status, it filters out businesses that have reached maximum capacity, ensuring that users only see actionable, available options.

**3\. Real-Time Notification Subsystem** To mitigate "wait anxiety," this subsystem maintains a persistent, low-latency communication channel between the server and client. Unlike traditional SMS systems that can be delayed, the **WebSocket Event Hub** delivers millisecond-level updates. It intelligently decides whether to send a silent in-app update (for active users) or a system-tray push notification (for background users).

**4\. Identity & Security Subsystem** This module functions as the gatekeeper of the platform. It enforces a "Zero Trust" policy where every API request is validated against a stateless JSON Web Token (JWT). Beyond simple login, it actively monitors user behavior, automatically triggering the **Reputation Manager** to suspend accounts that repeatedly violate the "No-Show" policy, thereby protecting providers from time-wasting interactions.

**5\. Analytics & Intelligence Subsystem** Operating asynchronously in the background, this subsystem transforms raw transaction logs into business value. It decouples reporting from live operations, ensuring that heavy statistical calculations such as determining "Peak Demand Hours" never degrade the performance of the active queue.

## **4.7. Persistent Data Management** {#4.7.-persistent-data-management}

Persistent Data Management, often referred to as **data modeling**, creates the structural blueprint for how the *Werefa* system captures, stores, and retrieves information over time. Unlike transient memory (RAM), this layer ensures that critical state, such as a user's position in a queue or a provider's service history is durably **preserved** against system failures or restarts.

### **4.7.1 Database Selection Rationale** {#4.7.1-database-selection-rationale}

The development team selected **PostgreSQL** as the primary Relational Database Management System (RDBMS). This decision is driven by two critical requirements:

* **ACID Compliance:**  
   Queue management requires strict atomicity. If a user joins a queue, the system must guarantee that **ticket creation** and **queue counter updates** happen simultaneously or not at all. PostgreSQL’s robust transaction management prevents "ghost tickets" or data corruption.

* **Geospatial Support (PostGIS):**  
   Unlike standard databases that store location as simple text or numbers, PostgreSQL (via the PostGIS extension) supports native **GEOGRAPHY** data types. This allows the system to perform complex spatial queries efficiently, such as:  
   "Find all open providers within a 5-kilometer buffer."

### **4.7.2 Object-Relational Mapping (ORM) Rules** {#4.7.2-object-relational-mapping-(orm)-rules}

To bridge the gap between the application's **object-oriented logic** (Node.js classes) and the relational database, the system employs a strict mapping strategy. This defines how in-memory objects are serialized into permanent tables.

We strictly adhere to the following mapping rules:

**Rule 1: Class-to-Table Mapping**

* Every major entity class in the system design is mapped to a distinct database table.  
* Example:  
  * User class → users table  
  * QueueTicket class → tickets table  
* Table names follow **snake\_case** to maintain SQL standards.

**Rule 2: Attribute-to-Column Mapping**

* Single-valued attributes (primitive types) are mapped directly to columns with compatible data types:  
  * String attributes (e.g., username) → VARCHAR(255)  
  * Boolean flags (e.g., is\_active) → BOOLEAN  
  * Timestamps (e.g., joined\_at) → TIMESTAMPTZ (timezone-aware timestamp)

**Rule 3: Relationship Mapping (Foreign Keys)**

* Relationships between entities are enforced via **foreign key constraints** to maintain referential integrity:  
  * **One-to-Many:** One Provider can have many Service Types. The service\_types table contains a foreign key provider\_id.  
  * **One-to-One:** For the relationship between a Ticket and a User, a unique constraint is applied to the foreign key to ensure a user holds only **one active spot** at a time.

**Rule 4: Spatial Data Mapping**

* Coordinate attributes (latitude/longitude) are **not stored as separate float columns**.  
* Instead, they are mapped to a single column of type GEOGRAPHY(Point, 4326).  
* This allows the usage of **spatial indices (GIST)** for high-performance proximity searches.

### **4.7.3 Normalization & Integrity** {#4.7.3-normalization-&-integrity}

* The schema is designed to meet **Third Normal Form (3NF)** standards to eliminate data redundancy.  
* Example: Customer details are stored **only** in the users table and referenced by ID in the tickets table.  
* This ensures that an update to a user's phone number is **instantly reflected** across all historical transactions.

## 

## 

## 

## 

## 

## 

## 

## 

## 

## 

## 

## 

## 

## 

## 

## 

## 

## 

## 

**Class-to-Database Mapping**

## **![][image22]**

## **![][image23]**

[F☙ure 22](#figur_clas2dbmap) : Class-to-Database Mapping

## **4.8. Component Diagram** {#4.8.-component-diagram}

The Component Diagram provides a structural view of the "Werefa" software system, illustrating the organization of physical implementation units and their dependencies. This diagram bridges the gap between the conceptual architecture and the actual codebase, defining how distinct software modules—such as the **Notification Service** and the **Geospatial Engine**—communicate via defined interfaces.

In the design of Werefa, a **Service-Based Component Architecture** is adopted. The central API Gateway acts as the primary orchestrator, exposing RESTful endpoints to client applications while routing internal logic to specialized backend components. Critical components include:

1. **Queue Controller:** The core logic unit responsible for enforcing FIFO rules, managing concurrency locks, and calculating wait times.  
2. **Socket Event Hub:** A dedicated component for managing persistent, full-duplex communication channels, enabling the real-time "push" functionality required for live queue updates.  
3. **PostGIS Spatial Module:** A specialized database component that encapsulates complex geometric calculations, decoupling geospatial logic from standard business rules.  
4. **Auth Middleware:** A reusable security component that intercepts all incoming requests to validate JWT signatures before they reach protected resources.

The diagram below visualizes these relationships, highlighting the "Provided" and "Required" interfaces that govern the interaction between the mobile client, the provider portal, and the server-side infrastructure.

![][image24]

Figure[F☙ure 23](#figur_systemdecomposition) : Werefa System Decomposition

## 

## 

## 

## 

## **4.9. Database Diagram** {#4.9.-database-diagram}

The following diagram illustrates the entity relationships between the core data tables of the Werefa system.

![][image25]

[F☙ure 24](#figur_dbdiagram) : Database Diagram

#### 

#### **4.10. Deployment Diagram** {#4.10.-deployment-diagram}

The Deployment Diagram illustrates the physical topology of the "Werefa" system, defining the execution environments (hardware nodes) and the software artifacts deployed within them. This view is critical for understanding the system's scalability, reliability, and network communication protocols.

The deployment architecture follows a **Containerized Cloud Strategy** to ensure consistency between development and production environments.

* **Client Nodes:** The system supports two distinct client environments: Android Smartphones (running the compiled Flutter APK) for Service Seekers and Web Browsers (Chrome/Firefox on Tablets or PCs) for Service Providers.  
* **Application Server Node:** The backend logic is hosted on a cloud-based Linux Server (e.g., AWS EC2 or DigitalOcean Droplet). To facilitate rapid deployment and isolation, the Node.js application is wrapped within a **Docker Container**, ensuring that dependencies are bundled with the executable.  
* **Database Server Node:** To ensure data persistence and performance, the PostgreSQL database (augmented with the PostGIS extension) runs on a dedicated database instance, separated from the application logic to prevent resource contention.  
* **Communication Protocols:** All communication between the Client Nodes and the Application Server occurs over secure channels. Standard API requests use **HTTPS (Port 443\)**, while real-time queue updates utilize **WSS (WebSocket Secure)** to maintain persistent, encrypted connections.

![][image26]

[F☙ure 25](#figur_deployment) : Deployment Diagram

## **4.11. Access Control** {#4.11.-access-control}

The "Werefa" platform implements a strict **Role-Based Access Control (RBAC)** mechanism to ensure that users can only interact with data relevant to their specific clearance level. This strategy minimizes the risk of unauthorized data modification and protects sensitive user information.

The system defines three primary actors:

1. **Service Seeker (User):** The end-customer joining queues.  
2. **Service Provider (Manager):** The business owner managing the queue.  
3. **System Administrator:** The super-user responsible for platform health and moderation.

The table below details the permission matrix, defining which actions (Create, Read, Update, Delete) each role can perform on specific system resources.

[Table 23](#table_ac) : Access Control

| Resource / Class | Service Seeker (App User) | Service Provider (Business) | System Administrator |
| :---- | :---- | :---- | :---- |
| **User Profile** | • Update: Own Profile • Read: Own Profile | • Read: Client Name (Limited) • Read: All Profiles • Update: Ban/Suspend User | • Read: All Profiles • Update: Ban/Suspend User |
| **Queue Ticket** | • Create: Join Queue • Read: Own Position • Delete: Cancel Own Ticket | • Create: Register Walk-In • Read: Full Queue List • Update: Call Next / Complete | • Read: All Active Queues • Delete: Force Close Ticket |
| **Business Profile** | • Read: View Details | • Update: Edit Info / Hours • Update: Set Geofence | • Create: Verify New Business • Update: Boost Visibility |
| **Reviews & Ratings** | • Create: Write Review • Read: Public Reviews | • Read: View Received Reviews • Update: Report Spam • Delete: Remove Offensive Content | • Read: All Reviews • Delete: Remove Offensive Content |
| **System Logs** | • None (Access Denied) | • Read: Own Demand Logs | • Read: All System Logs • Delete: Archive Old Logs |
| **Admin Dashboard** | • None (Access Denied) | • None (Access Denied) | • Read: Global Analytics • Update: System Config |

# 

# **Chapter 5:**  {#chapter-5:}

# **Implementation** {#implementation}

## **5.1. Overview** {#5.1.-overview}

The implementation phase constitutes the translation of the "Werefa" system's architectural design into a functional, deployable software product. This chapter comprehensively details the engineering processes, coding methodologies, and technical environment established to build the Hybrid Queue Management System.

The execution of this phase adhered to the **Agile Scrum Methodology**, broken down into two-week sprints. This iterative approach allowed the development team to isolate the complex subsystems, specifically the geospatial logic and the real-time websocket synchronization and develop them in parallel before integration.

The implementation focuses on three distinct layers:

1. **The Client Layer:** Developing high-performance interfaces for both Android (Flutter) and Web (React.js) to ensure accessibility for diverse user groups in Adama.  
2. **The Application Layer:** Constructing a modular monolithic backend using **Node.js (NestJS)** to handle business logic, concurrency locking, and state management.  
3. **The Persistence Layer:** Implementing a **PostgreSQL** database schema optimized with **PostGIS** for high-speed spatial queries.

By strictly adhering to the design specifications outlined in Chapter 4, this phase ensures that the final product not only meets functional requirements but also adheres to non-functional constraints regarding scalability, security, and response latency.

## **5.2. Coding Standards** {#5.2.-coding-standards}

To maintain codebase uniformity, readability, and long-term maintainability, the development team enforced a rigorous set of coding standards. These standards were integrated into the development workflow using static analysis tools (ESLint for JavaScript/TypeScript and flutter\_lints for Dart) to prevent non-compliant code from being committed.

### 

### 

### **5.2.1. Naming Conventions** {#5.2.1.-naming-conventions}

A strict naming strategy was applied to distinguish between variable scopes, class definitions, and database entities instantly.

* **Classes & Components (PascalCase):** All class definitions, React components, and Flutter widgets utilize PascalCase to signify instantiation capability.  
  * *Example:* QueueController, UserProfileCard, AuthService.  
* **Variables & Functions (camelCase):** Local variables, class methods, and function parameters use camelCase for readability.  
  * *Example:* calculateWaitTime(), userCurrentLocation, isQueueFull.  
* **Constants & Environment Variables (UPPER\_SNAKE\_CASE):** Immutable values and configuration settings are capitalized to indicate their static nature.  
  * *Example:* MAX\_RETRY\_ATTEMPTS, JWT\_SECRET\_KEY, DEFAULT\_GEOFENCE\_RADIUS.  
* **Database Schema (snake\_case):** To align with PostgreSQL standards, all table names and column attributes use snake\_case.  
  * *Example:* table: queue\_tickets, column: created\_at, column: provider\_id.

### **5.2.2. Directory Structure & Modularity** {#5.2.2.-directory-structure-&-modularity}

The project follows a **Feature-Based Architecture** rather than a Layer-Based one. This ensures that all code related to a specific feature (e.g., "Authentication") is co-located, making the system easier to scale.

* **Backend Structure (NestJS):**  
  * /src/modules/auth/ (Contains Controller, Service, and Repository for Auth).  
  * /src/modules/queue/ (Contains Queue Logic, Events, and DTOs).  
  * /src/common/ (Shared utilities, Guards, and Interceptors).  
* **Frontend Structure (Flutter):**  
  * /lib/features/ (Each screen or flow is a distinct feature).  
  * /lib/core/ (Network clients, Error handling, Theme configs).

### **5.2.3. Error Handling Standards** {#5.2.3.-error-handling-standards}

A global exception handling strategy was implemented to ensure the system fails gracefully without crashing or exposing sensitive stack traces to the user.

* **Try-Catch Blocks:** All asynchronous operations (Database calls, API requests) are wrapped in try-catch blocks.  
* **Standardized HTTP Responses:** The backend is configured to return strict HTTP Status Codes:  
  * 200 OK / 201 Created: For successful operations.  
  * 400 Bad Request: For validation errors (e.g., missing inputs).  
  * 401 Unauthorized: For invalid or missing JWT tokens.  
  * 500 Internal Server Error: For unhandled system failures (logged internally).

### **5.2.4. Version Control Guidelines** {#5.2.4.-version-control-guidelines}

The team utilized **Git** for version control, strictly adhering to the **Conventional Commits** specification to automate changelog generation and semantic versioning.

* feat: introduces a new feature (e.g., feat: add geofence validation logic).  
* fix: patches a bug (e.g., fix: resolve websocket connection timeout).  
* refactor: code change that neither fixes a bug nor adds a feature (e.g., refactor: optimize wait time algorithm).

## **5.3. Development Tools** {#5.3.-development-tools}

A comprehensive suite of modern software development tools was utilized to facilitate the coding, testing, debugging, and deployment processes. These tools were selected based on their industry adoption, community support, and compatibility with the chosen "Hybrid" architecture.

[Table 24](#table_devtools) : Development Tools

| Category | Tool Name | Description & Usage in Project |
| :---- | :---- | :---- |
| **Integrated Development Environments (IDEs)** | **Visual Studio Code** | The primary editor for the Web Portal (React) and Backend (Node.js). Selected for its robust extension ecosystem (Prettier, ESLint, Docker extension) and integrated terminal. |
|  | **Android Studio** | Essential for Flutter development. Used specifically for configuring Android Emulators (AVD), managing SDK versions, and debugging native Gradle build scripts. |
| **Version Control** | **Git & GitHub** | **Git** handled local source code management, while **GitHub** served as the remote repository. GitHub Actions were configured for basic Continuous Integration (CI) to run linting checks on Pull Requests. |
| **API Testing & Debugging** | **Postman** | Utilized to simulate HTTP requests to the backend API. Key for testing authentication flows and payload validation before the frontend UI was built. |
|  | **Socket.io Admin UI** | A specialized tool used to visualize and debug real-time WebSocket events, ensuring that "rooms" and "namespaces" were correctly isolating traffic between providers. |
| **Database Management** | **pgAdmin 4** | The standard GUI for PostgreSQL. Used to execute complex SQL queries manually, visualize table relationships, and verify the accuracy of **PostGIS** spatial data points. |
| **Design & Prototyping** | **Figma** | Used during the implementation phase to reference pixel-perfect UI designs, ensuring the coded frontend matched the approved high-fidelity mockups. |
| **Containerization** | **Docker Desktop** | Used to containerize the Backend and Database services. This ensured that all developers worked in an identical environment, eliminating "it works on my machine" issues. |

\`**5.4. Prototype**  
The prototyping phase served as a critical bridge between conceptual design and final implementation, allowing for the validation of user flows before committing to code. The evolution of the "Werefa" prototype followed a three-stage iterative process:

1. **Low-Fidelity Wireframes (Paper & Whiteboard):** The initial iteration focused on layout and navigation structure. Sketches were created to map out the "Join Queue" journey, identifying potential bottlenecks such as the complexity of the "Service Selection" screen for non-technical users.  
2. **High-Fidelity Interactive Mockups (Figma):** A pixel-perfect design system was established, defining the "Emerald Green" (Active) and "Amber" (Warning) color semaphores. This stage simulated micro-interactions, such as the countdown timer animation and the "You are too far" geofence warning, to test usability heuristics.  
3. **Functional MVP (Minimum Viable Product):** The final prototype stage involved a "Steel Thread" implementation—building a single, end-to-end flow where a user could join a queue on a mobile device and a provider could see that ticket appear instantly on a separate web dashboard. This verified the feasibility of the WebSocket synchronization architecture.

The following figures illustrate the high-fidelity user interfaces developed during the second phase of prototyping. These mockups demonstrate the final visual design system, including the color-coded status indicators and the responsive layout adapted for mobile and desktop environments

![][image27]

[F☙ure 26](#figur_dashboard) : Dashboard

![][image28]

[F☙ure 27](#figur_service) : Services

## 

## 

| ![][image29] | ![][image30] |
| :---- | :---- |

## 

[F☙ure 28](#figur_search) : Search

| ![][image31] | ![][image32] |
| :---- | :---- |

## 

[F☙ure 29](#figur_queue) : Queue

## **5.5. Implementation Detail** {#5.5.-implementation-detail}

This section provides a technical breakdown of the constructed system, categorized into Client-Side interfaces, Server-Side architecture, and the Algorithmic Intelligence used for predictive analysis.

### **5.5.1. Client-Side Implementation** {#5.5.1.-client-side-implementation}

The client layer is composed of two distinct applications, each optimized for its specific hardware environment and user persona.

A. Service Seeker Application (Mobile)

The mobile application targets end-users and is built using Flutter (Dart) to ensure native performance on both Android and iOS from a single codebase.

* **Architecture:** The app follows the **BLoC (Business Logic Component)** pattern. This separates the User Interface (UI) from the logic, ensuring that a state change—such as a ticket status moving from "Waiting" to "Called"—triggers a streamlined UI rebuild without affecting the rest of the application tree.  
* **Geolocation Engine:** The implementation utilizes the geolocator package to access the device’s GPS hardware. A background service continuously calculates the haversine distance between the user and the provider. If the user exits the defined geofence radius while in a queue, the client triggers a local notification warning them to return.  
* **Offline Resilience:** To handle intermittent network connectivity common in Adama, the app implements **Hive**, a lightweight NoSQL database. This caches the active ticket state locally, allowing the user to view their ticket number even if they temporarily lose internet access.

B. Service Provider Portal (Web)

The provider interface is a Single Page Application (SPA) built with React.js.

* **Real-Time Dashboard:** The core component is the "Queue Monitor," which hooks into the Socket.io-client library. Instead of polling the server every few seconds (which wastes bandwidth), the application maintains an open WebSocket connection. When the server emits a TICKET\_JOINED event, the React state updates instantly, appending the new ticket to the list.  
* **Audio Feedback Integration:** To ensure providers are alerted to new customers even when looking away from the screen, the implementation leverages the browser's **Web Audio API** to play a distinct chime sound whenever a remote join occurs.

### **5.5.2. Server-Side Implementation** {#5.5.2.-server-side-implementation}

The backend acts as the central orchestrator, implemented as a **Modular Monolith** using **Node.js** with the **NestJS** framework. This choice provides a structured, opinionated architecture similar to Angular, ensuring scalability.

* **Hybrid Communication Layer:** The server implements a dual-protocol gateway:  
  * **REST API (Express):** Handles stateless, transactional operations such as User Registration, Authentication (JWT), and fetching static Business Profiles.  
  * **WebSocket Gateway (Socket.io):** Handles stateful, real-time interactions. Upon connection, the server validates the user's JWT and assigns their socket to a specific "Room" (e.g., room\_provider\_123). This ensures that queue updates are broadcast only to relevant users, minimizing data overhead.  
* **Concurrency & Locking:** A critical implementation detail is the **Mutex Locking Mechanism** using Redis. This prevents "Race Conditions" where two providers might accidentally call the same ticket simultaneously. When a "Call Next" request is received, the server acquires an atomic lock on the queue ID, processes the transaction, and then releases the lock.  
* **Spatial Data Processing:** Location queries are offloaded to the **PostGIS** database extension. The implementation uses the ST\_DWithin SQL function to perform highly optimized "Nearest Neighbor" searches, allowing the system to filter providers within a 5km radius in milliseconds.

### **5.5.3. Algorithmic Prediction Logic** {#5.5.3.-algorithmic-prediction-logic}

While the system does not employ Deep Neural Networks (which would be computationally excessive for this use case), it implements a robust **Statistical Regression Algorithm** to predict Estimated Wait Times (EWT).

* **Data Preprocessing:** The system maintains a DemandLog table that records the precise start\_time and end\_time of every completed service.  
* **The Algorithm (Weighted Moving Average):** To predict the wait time for a new user, the system does not use a static global average. Instead, it calculates a **Weighted Moving Average (WMA)** of the last 10 completed services for that specific provider.  
  * **Formula:** $EWT \= \\sum\_{i=1}^{n} (Duration\_i \\times Weight\_i)$  
* **Weighting Strategy:** The algorithm assigns higher weights to the most recent 3 transactions. This allows the system to adapt dynamically to the provider's *current* working speed (e.g., if they are tired and working slower in the afternoon), resulting in a more accurate prediction than a simple arithmetic mean.

### **References**

\[1\] J. D. C. Little, "A Proof for the Queuing Formula: L \= λW," *Operations Research*, vol. 9, no. 3, pp. 383–387, 1961\.

\[2\] D. Norman, *The Design of Everyday Things*, 2nd ed. New York, NY, USA: Basic Books, 2013\.

\[3\] R. S. Pressman and B. R. Maxim, *Software Engineering: A Practitioner's Approach*, 8th ed. New York, NY, USA: McGraw-Hill Education, 2015\.

\[4\] M. Fowler, "Patterns of Enterprise Application Architecture," Boston, MA, USA: Addison-Wesley, 2002\.

\[5\] A. K. Erlang, "The Theory of Probabilities and Telephone Conversations," *Nyt Tidsskrift for Matematik B*, vol. 20, pp. 33–39, 1909\.

\[6\] "React Documentation," Meta Open Source. \[Online\]. Available: [https://react.dev/](https://react.dev/). \[Accessed: Dec. 2025\].

\[7\] "Socket.IO: Bidirectional and Low-Latency Communication," Socket.IO. \[Online\]. Available: [https://socket.io/docs/v4/](https://socket.io/docs/v4/). \[Accessed: Dec. 2025\].

\[8\] Y. Bassil, "A Simulation Model for the Analysis of Queuing Systems in Banks," *Journal of Comparison*, vol. 3, no. 1, pp. 12–18, 2012\.

\[9\] K. Patel and S. Patel, "Internet of Things-IOT: Definition, Characteristics, Architecture, Enabling Technologies, Application & Future Challenges," *International Journal of Engineering Science and Computing*, vol. 6, no. 5, pp. 6122–6131, 2016\.

\[10\] "PostgreSQL: The World's Most Advanced Open Source Relational Database," PostgreSQL Global Development Group. \[Online\]. Available: [https://www.postgresql.org/](https://www.postgresql.org/). \[Accessed: Dec. 2025\].

\[11\] M. Weiser, "The Computer for the 21st Century," *Scientific American*, vol. 265, no. 3, pp. 94–104, 1991\.

\[12\] "Ethio Telecom: Annual Performance Report 2023/24," Ethio Telecom, Addis Ababa, Ethiopia, Rep., 2024\.

\[13\] I. Sommerville, *Software Engineering*, 10th ed. London, UK: Pearson, 2016\.

\[14\] "Google Maps Platform Documentation: Geolocation API," Google Developers. \[Online\]. Available: [https://developers.google.com/maps/documentation/geolocation/overview](https://developers.google.com/maps/documentation/geolocation/overview). \[Accessed: Dec. 2025\].

\[15\] J. Nielsen, "Usability Engineering," San Francisco, CA, USA: Morgan Kaufmann, 1993\.
