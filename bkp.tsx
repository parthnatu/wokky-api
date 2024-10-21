
import { useEffect, useState } from "react";
import React = require("react");
import {
  HashRouter,
} from "react-router-dom";




function Main() {
  const [latitude, setLatitude] = useState(0);
  const [longitude, setLongitude] = useState(0);
  const [userDecided, setUserDecided] = useState(false);;

  var options = {
    enableHighAccuracy: true,
    timeout: 5000,
    maximumAge: 0,
  };
  function success(pos: { coords: any; }) {
    var crd = pos.coords;
    setLatitude(crd.latitude);
    setLongitude(crd.longitude);
    setUserDecided(true);
  }

  function errors(err: { code: any; message: any; }) {
    console.warn(`ERROR(${err.code}): ${err.message}`);
    setUserDecided(true);
  }

  useEffect(() => {
    if (navigator.geolocation) {
      navigator.permissions
        .query({ name: "geolocation" })
        .then(function (result) {
          console.log(result);
          if (result.state === "granted") {
            //If granted then you can directly call your function here
            navigator.geolocation.getCurrentPosition(success, errors, options);
          } else if (result.state === "prompt") {
            //If prompt then the user will be asked to give permission
            navigator.geolocation.getCurrentPosition(success, errors, options);
          } else if (result.state === "denied") {
            //If denied then you have to show instructions to enable location
          }
        });
    } else {
      console.log("Geolocation is not supported by this browser.");
    }
  });

  return userDecided ? (
    <HashRouter>
      <div>
        <h1>Simple SPA</h1>
        <h1>Coords : {latitude} , {longitude}</h1>
      </div>
    </HashRouter>
  ) : <h1>Loading...</h1>;
}

export default Main;
