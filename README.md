# tpp-onboarding-application
The Third Party Provider(tpp) onboarding application allows creation of an Software Statement Assertions(SSA) and onboarding with Brokers. It acts as a Frontend to the [Directory](https://github.com/alphagov/trust-framework-directory-prototype) which Brokers can use to register onto the Directory.

## Running the Onboarding Application

### Prerequisites
* Python3

### Starting the app
The Onboarding/Registration application can be started independently by running the `startup-registration.sh` or together with the rest of the Trust Framework Prototype applications using the [start-all-services.sh](https://github.com/alphagov/stub-oidc-broker/blob/master/start-all-services.sh) in the Stub OIDC Broker repository.

When running locally the registration page can be accessed using http://localhost:5000.

### TPP Onboarding Application runs on the PAAS
* To deploy TPP Onboarding Application simply login to the PAAS and select the build-learn space. 
* Run `cf push` and this will deploy the app.
* The application on the PAAS can be accessed using https://onboarding-prototype.cloudapps.digital/.