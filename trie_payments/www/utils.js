async function getPaymentDetails(orderId){
    //load data from backend using orderId here
    const responsePaymentRecord = await new Promise((resolve, reject) => {
        frappe.call({
            method: "trie_payments.trie_payment_functions.fetching_payment_details_call",
            type: "POST",
            args: { order_id: orderId },
            callback: function(response) {
                if (response.message) {
                    console.log("----------", response.message)
                    resolve(response.message);
                } else {
                    reject("Failed to fetch payment details");
                }
            }
        })
    });

    //change the name and amount value accordingly
    return new Promise ((resolve,reject)=>{
        setTimeout(()=>{
            resolve({
                name: responsePaymentRecord.senders_name,
                amount: responsePaymentRecord.order_currency+ " "+ responsePaymentRecord.order_amount,
                time: responsePaymentRecord.payment_time
            })
        },3000)
    });
};


// Utility function to set text content of an element
function setElementText(element, text) {
    if (element) {
        element.textContent = text;
    }
}

// // Function to fetch payment details
// async function getPaymentDetails(orderId) {
//     // Mocking backend data loading

    // const responsePaymentRecord = await new Promise((resolve, reject) => {
    //     frappe.call({
    //         method: "trie_payments.trie_payment_functions.fetching_payment_details_call",
    //         type: "POST",
    //         args: { order_id: orderId },
    //         callback: function(response) {
    //             if (response.message) {
    //                 console.log("----------", response.message)
    //                 resolve(response.message);
    //             } else {
    //                 reject("Failed to fetch payment details");
    //             }
    //         }
    //     });

//     const mockData = await new Promise((resolve, reject) => {
//         console.log("***********", responsePaymentRecord)
//         console.log("******amount*****", responsePaymentRecord.order_amount)
//         console.log("******currency*****", responsePaymentRecord.order_currency)
//         setTimeout(() => {
//             resolve({
//                 name: "Faizal",
//                 amount: "AED 100",
//                 time: "2024-01-01 12:00:00"
//             });
//         }, 3000);
//     });]


//     // Return the fetched data (mock data here)
//     return mockData;
// }

// Example usage of the above functions
// (async () => {
//     const orderId = "12345"; // Example order ID
//     const paymentDetails = await getPaymentDetails(orderId);

//     const nameElement = document.getElementById('name');
//     const amountElement = document.getElementById('amount');

//     setElementText(nameElement, paymentDetails.name);
//     setElementText(amountElement, paymentDetails.amount);
// })();



// const paymentRecordDetails = async () => {
//     const token = localStorage.getItem("token");
//     const gameName = localStorage.getItem("SelectedGame");
//     $.ajax({
//       url: `${base_url}/api/method/trie_payments.trie_payment_functions.fetching_payment_details_call?order_id=${orderId}`,
//       method: "GET",
//       headers: {
//         Authorization: `Bearer ${token}`,
//         "Content-type": "application/json",
//         Accept: "application/json",
//       },
//       data: {},
//       datatype: "json",
//       success: function (result) {
        
//       },
//       error: function (error) {
//         console.log(error.exception);
//       },
//     });
//   };