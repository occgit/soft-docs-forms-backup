define(['jquery',
    'knockout',
    'vmBase',
    'integration',
    'notify',
    'user',
    'template/autosize.min',
    'template/jquery.maskedinput',
    './liveViewModel.js',
    'package',
    'https://webapps.oaklandcc.edu/cdn/formUtils-v9.js',
    /*-- WARNING: Uncommenting the line of code below will allow you to use Etrieve Extenders on this form.
    Currently, Etrieve Extenders are only compatible with cloud based instances of Etrieve.
    If you are unsure if you can utilize Extenders, please contact your institution's Etrieve Administrator.*/
    'https://softdocscdn.etrieve.cloud/extenders/extenders.min.js'
], function viewmodel($, ko, vm, integration, notify, user, autosize, maskedinput, liveVM, pkg, formUtils) {

    // Form-scoped required indicators manager.
    // Safe to call before init. Calls to setRequired(...) queue until afterLoad runs init(vm).
    var requiredIndicators = formUtils.createRequiredIndicators();

    //This function is used to set the autosize function on textareas with a class of autosizeareas.
    //Uncomment to use.
    //autosize($('.autosizeareas'));


    /*
    These functions are used to set the masking of fields. There are 3 example classes below you can use.
    If you need to add another row, simple copy one of the examples below and edit the class name and the mask
    */
    $('.maskphone').mask('(999)999-9999? ext:9999');
    $('.maskzip').mask('99999?-9999');
    $('.maskssn').mask('999-99-9999');
    /*End masking functions*/

    //Parameters:
    //  $: jQuery object. Additional documentation found at api.jquery.com

    //  ko: knockoutjs object. Additional documentation found at knockoutjs.com

    //  vm: is a base viewmodel object that enables you to interact with observable inputs on the
    //  view.html.  Observables for all inputs, selects, and textareas will be added when the
    //  viewmodel is bound to the view.  vmBase has functions to aid in adding additional observable
    //  properties to itself such as addObservables, addObservableArrays which both take a comma-
    //  separated string of names.

    //  user: The user parameter includes data associated with the current user including isInLibrary,
    //  isInDrafts, isInActivity, isOriginator, DisplayName, UserName, hasGroupOrRole, Email.

    //  integration: has functions for directly calling integration sources configured on the server
    //  integration.first: takes Source Code and an optional Parameter Object, returning a single object
    //  integration.all: takes Source Code and an optional Parameter Object, returning an array of objects
    //  integration.add: takes Source Code and a Parameter Object, returning an array of objects
    //  integration.update: takes Source Code and a Parameter Object, returning an array of objects
    //  integration.delete: takes Source Code and a Parameter Object, returning an array of objects

    //  notify: method that display a toast notification, it requires the next parameters
    //      - toastrType: string indicating the type of toast notification, could have the next values:
    //          - success
    //          - warning
    //          - error
    //      - message: string indicating the message to display on notification
    //      - title: string indicating the title for the notification

    //  pkg: The pkg viewmodel object includes parameters which return properties 
    //  around the package and the package state throughout the workflow.
    //  stepCode, stepName, isAtStep, isExporting.

    //The following methods are lifecycle callbacks that will be called as described
    //if they are returned on the viewmodel object, but they are not required.

    //NOTE: if a JavaScript Promise is returned from any Lifecycle Callback, the process will wait until
    //the Promise is resolved before continuing.  Additionally, if an Integration source or any other
    //asynchronous method is called directly within one of these functions, it is required that a Promise
    //be returned in order to guarantee these methods are called in a predictable, sequential manner.

    //Loading Lifecycle Callbacks:
    //Parameters:
    //  source:
    //  If the form is configured to receive integration sources onLoad or onOrigination,
    //  they will be passed on the source parameter. onLoad sources will be available
    //  every time the form is loaded while onOrigination sources will only be available
    //  when user.isInLibrary is true.

    //  inputValues:
    //  inputValues.first(id) takes an input id & returns a single value if one exists.
    //  inputValues.all(id) takes an input id & returns an array of values if any exist.
    //  inputValues.audit(id) takes an input id & returns an array of audit history values if any exist.
    //  inputValues.list is an array of all values sent from the server that will be loaded
    //      into this form after setDefaults and prior to afterLoad.  This should only be needed if
    //      it is necessary to filter on something other than input id.

    function getTodayDate() {
        const today = new Date();

        // Pad month/day with leading zero if needed
        const month = String(today.getMonth() + 1).padStart(2, '0');
        const day = String(today.getDate()).padStart(2, '0');
        const year = today.getFullYear();

        return `${month}/${day}/${year}`;
    }

    function makeAutoCompleteReadOnly(elementID) {
        $(`#${elementID}`)
            .prop('disabled', true)
            .attr({
                tabindex: '-1',
                'aria-disabled': 'true'
            })
            .css({
                'pointer-events': 'none',
                'background-color': '#f5f5f5',
                'color': '#555'
            });
    }

    function disableRadio(elementID) {
        const $el = $(`#${elementID}`);
        $el.prop('disabled', true)
            .attr('aria-disabled', 'true')
            .css({ opacity: '0.6', cursor: 'not-allowed' });
    }

    function makeAllFieldsRequired() {
        makeAutoCompleteReadOnly('supervisorCoordinator');

        $("#ddInternational").prop("disabled", true);
        $("#visaType").prop("readonly", true);

        vm.educationRow().forEach(function (dynamicListRow, index) {
            dynamicListRow.school.disabled = false;
            dynamicListRow.dates.disabled = false;
            dynamicListRow.degree.disabled = false;
            dynamicListRow.programOfStudy.disabled = false;
            dynamicListRow.gpa.disabled = false;
            dynamicListRow.currentCreditHours.disabled = false;
            dynamicListRow.totalAccruedCredit.disabled = false;
            dynamicListRow.expectedGradDate.disabled = false;
            dynamicListRow.creditEarnedProgramArea.disabled = false;
            dynamicListRow.specializedTraining.disabled = false;
            dynamicListRow.scholarshipsAwards.disabled = false;

            $(".btn-delete-item").prop("disabled", false);
        });

        $(".addEducationBtn").prop('disabled', false);
        $(".removeEducationBtn").prop('disabled', false);

        vm.employmentRow().forEach(function (dynamicListRow, index) {
            dynamicListRow.company.disabled = false;
            dynamicListRow.fromDate.disabled = false;
            dynamicListRow.toDate.disabled = false;
            dynamicListRow.jobTitle.disabled = false;

            $(".btn-delete-item").prop("disabled", false);
        });

        $(".addEmploymentBtn").prop('disabled', false);
        $(".removeEmploymentBtn").prop('disabled', false);

        requiredIndicators.setRequired('convictedCriminalY', true);
        requiredIndicators.setRequired('authorizeY', true);


        for (let i = 1; i <= 15; i++) {
            requiredIndicators.setRequired(`initial${i}`, true);
        }

        requiredIndicators.setRequired('eligibleToWork', false);
        requiredIndicators.setRequired('veteran', false);
        requiredIndicators.setRequired('accommodations', true);


    }

    function makeAllFieldsReadOnly() {
        makeAutoCompleteReadOnly('supervisorCoordinator');

        $("#ddInternational").prop("disabled", true);
        $("#visaType").prop("readonly", true);

        vm.educationRow().forEach(function (dynamicListRow, index) {
            dynamicListRow.school.disabled = true;
            dynamicListRow.dates.disabled = true;
            dynamicListRow.degree.disabled = true;
            dynamicListRow.programOfStudy.disabled = true;
            dynamicListRow.gpa.disabled = true;
            dynamicListRow.currentCreditHours.disabled = true;
            dynamicListRow.totalAccruedCredit.disabled = true;
            dynamicListRow.expectedGradDate.disabled = true;
            dynamicListRow.creditEarnedProgramArea.disabled = true;
            dynamicListRow.specializedTraining.disabled = true;
            dynamicListRow.scholarshipsAwards.disabled = true;

            $(".btn-delete-item").prop("disabled", true);
        });

        $(".addEducationBtn").prop('disabled', true).attr('aria-disabled', 'true');
        $(".removeEducationBtn").prop('disabled', true).attr('aria-disabled', 'true');

        vm.employmentRow().forEach(function (dynamicListRow, index) {
            dynamicListRow.company.disabled = true;
            dynamicListRow.fromDate.disabled = true;
            dynamicListRow.toDate.disabled = true;
            dynamicListRow.jobTitle.disabled = true;

            $(".btn-delete-item").prop("disabled", true);
        });

        $(".addEmploymentBtn").prop('disabled', true).attr('aria-disabled', 'true');
        $(".removeEmploymentBtn").prop('disabled', true).attr('aria-disabled', 'true');

        disableRadio('convictedCriminalY');
        disableRadio('convictedCriminalN');

        $("#initial1").prop("readonly", true);
        $("#initial2").prop("readonly", true);
        $("#initial3").prop("readonly", true);
        $("#initial4").prop("readonly", true);
        $("#initial5").prop("readonly", true);
        $("#initial6").prop("readonly", true);
        $("#initial7").prop("readonly", true);
        $("#initial8").prop("readonly", true);
        $("#initial9").prop("readonly", true);
        $("#initial10").prop("readonly", true);
        $("#initial11").prop("readonly", true);
        $("#initial12").prop("readonly", true);
        $("#initial13").prop("readonly", true);
        $("#initial14").prop("readonly", true);
        $("#initial15").prop("readonly", true);

        $("#eligibleToWork").prop("disable", true);
        $("#veteran").prop("disable", true);
        $("#accommodations").prop("disable", true);
        $("#visaType").prop("disable", true);

        $("#explainAccommodations").prop("disabled", true);
        disableRadio('authorizeY');
        disableRadio('authorizeN');
    }

    vm.onLoad = function onLoad(source, inputValues) {
        //  This takes place after applyBindings has been called and has added input observables to the
        //  viewmodel (vm) and before values are loaded into the form.  This method is ideal for
        //  populating dropdowns, select options and other operations that need to take place every
        //  time the form is loaded.

        //  WARNING: It is not recommended to set input values during onLoad because it is not guaranteed
        //  to save values to the server.

        // $('.developer').hide();
    };

    vm.setDefaults = function setDefaults(source, inputValues) {
        //  This method is called after values from the server are loaded into the form inputs and before
        //  afterLoad is called.

        //  WARNING: if an integration source is called directly to retrieve values and populate inputs
        //  with default values, setDefaults must return the integration source promise.  If it doesn't,
        //  a form draft may be created every time a user opens the form and more importantly the values
        //  may not be saved to the server.

        if (user.isInLibrary) {
            //  Input Values set here will be saved to the server when the user makes a form
            //  instance creating action: changing an input value or clicking submit.
            integration.all('GET_Current_Academic_Year', {}).then(function (academicYear) {
                let acadYr = academicYear[0].AcademicYear;
                vm.academicYear(acadYr);
            });

            let studentID = vm.originatorErpId();
            integration.first('Web_Ethos_Get_Persons_by_Colleague_ID', { personID: studentID }).then(function (personResults) {
                console.log('Person Results', personResults);
                if (personResults) {
                    let addressGUID = personResults.addresses[0].address.id;
                    let phone = personResults.phones[0].number;

                    vm.studentPhoneNumber(phone);

                    integration.all('Web_Ethos_Get_Address_By_Address_GUId', { addressGUID: addressGUID }).then(function (address) {
                        console.log('Address:', address);

                        vm.address(address.addressLines[0]);
                        vm.city(address.place.country.subRegion.title);
                        vm.state(address.place.country.region.title);
                        vm.zipCode(address.place.country.postalCode);

                    });
                } else {
                    notify('error', 'Person not found');
                    $('.loading').hide();
                }
            });

        } else {
            //  Input Values set here will be saved to the server immediately.
            //  CAUTION: It is recommended to only set the values of inputs that haven't been populated by
            //  prior users.  Inputs that already have values saved to the server will be overridden with
            //  values set in this method.

        }

        if (pkg.isAtStep('Start')) {

            //If Are You an international student is No the entire form will display else stay hidden
            $('.f1').hide();
            $('.isoSignature').hide();

        }

        //Form will route here ONLY if the student selects Yes from Are you an international student dropdown
        if (pkg.isAtStep('F1')) {

            $('.f1').hide();
            $('.isoSignature').show();

            //Only Student Information is visible at this step so only the supervisor needs to be read only
            makeAutoCompleteReadOnly('supervisorCoordinator');

        }

        //Form will route here ONLY if the International Student's Office approves the internship/co-op process for student
        if (pkg.isAtStep('F1StudentESign')) {

            $('.f1').show();
            $('.isoSignature').show();

            $("#isoSignature").prop("readonly", true);

            //Once approved by the F1 office the other sections on the form are available for the student to complete
            makeAllFieldsRequired();

        }

        if (pkg.isAtStep('FacultySupervisor')) {

            makeAllFieldsReadOnly();

        }

        vm.studentSignature.subscribe(function (sig) {
            vm.studentSignDate(getTodayDate());
        });

        vm.isoSignature.subscribe(function (sig) {
            vm.studentSignDate(getTodayDate());
        });

        vm.ddInternational.subscribe(function (int) {
            if (int == 'Yes') {
                $('.f1').hide();
                $('.isoSignature').hide();
                vm.isInternationalStudent('Yes');
            } else if (int == 'No') {
                $('.f1').show();
                $('.isoSignature').hide();
                vm.isInternationalStudent('No');
            }
        });
    };

    vm.afterLoad = function afterLoad() {
        //  This method is called after setDefaults has been called.

        //  WARNING: It is not recommended to set input values during afterLoad because it is not guaranteed
        //  to save values to the server.

        //Initialize FormBuilder created form specific code
        liveVM.afterLoadEditsForVM();
        // Initialize required indicators after VM bindings and form DOM are ready.
        // This replays any queued setRequired(...) calls made earlier in setDefaults.
        requiredIndicators.init(vm);
        /*
        //  This is resizing the textarea's when the form loads incase it is pulling in real data.
        var ta = document.querySelector('.autosizeareas');
        var evt = document.createEvent('Event');
        evt.initEvent('autosize:update', true, false);
        ta.dispatchEvent(evt);
        */
        autosize($('textarea'));
    };

    //Submitting Lifecycle Callbacks:
    //Parameters:
    //  form.attachmentCount: integer

    //In order to stop the Submitting Lifecycle and prevent this form from moving to the next step in the workflow
    //process, add the following to any of the functions below:
    //    throw new Error('reason placed here will be displayed to the user');

    vm.onSubmit = function onSubmit(form) {
        //  This method is called when the Submit button is clicked and before calling beforeRequired.
        //  This normally occurs in the Forms Library, but may occur in the Inbox when a package is
        //  returned to Originator.
        if (pkg.isAtStep('Start')) {

            var internationalStudent = document.getElementById("ddInternational");
            if (internationalStudent.value == 'Yes') {
                requiredIndicators.setRequired('visaType', true);
            }

        }
    };

    vm.onApprove = function onApprove(form) {
        //  This method is called when the Approve button is clicked and before calling beforeRequired.
        if (pkg.isAtStep('F1')) {
            requiredIndicators.setRequired('isoSignature', true);
        }
    };

    vm.onDecline = function onDecline(form) {
        //  This method is called when the Decline button is clicked and before calling beforeRequired.

    };

    vm.beforeRequired = function beforeRequired(form) {
        //  This method is called after onSubmit, onApprove or onDecline and before validating the forms required fields.
        // Enable native DOM `required` attributes at validation time.
        // This prevents fields from appearing invalid on initial load,
        // while still allowing browser validation during submit.
        requiredIndicators.applyNativeRequiredForValidation();
    };

    vm.afterRequired = function afterRequired(form) {
        //  This method is called after the required inputs on the form have been confirmed to have values.
        requiredIndicators.clearNativeRequired();
    };

    vm.onOptOut = function onOptOut(form) {
        //  This method is called after the required inputs on the form have been confirmed to have values.

    };

    vm.onESignSubmit = function onESignSubmit(form) {
        //  This method is called after the required inputs on the form have been confirmed to have values.
        if (pkg.isAtStep('F1StudentESign')) {
            requiredIndicators.setRequired('studentSignature', true);
        }
    };

    return vm;
});
