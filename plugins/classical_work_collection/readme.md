This is the documentation for version 0.1 "Classical Work Collections". There may be beta versions later than this - check [my github site](https://github.com/MetaTunes/picard-plugins/releases) for newer releases.

This plugin adds a context menu 'add works to collections', which operates from track or album selections
regardless of whether a file is present. It presents a dialog box showing available work collections. Select the 
collection(s)and a confirmation dialog appears. Confirming will add works from all the selected tracks to the 
selected collections. 
If the plugin 'Classical Extras' has been used then all parent works will also be added.

The first dialog box gives options:
* Maximum number of works to be added at a time: The default is 200. More than this may result in "URI too large" error (even though the MB documentation says 400 should work). If a "URI too large" error occurs, reduce the limit."
* Provide analysis of existing collection and new works before updating: Selecting this (the default) will provide information about how many of the selected works are already in the selected collection(s) and only new works will be submitted. Deselecting it will result in all selected works being submitted, but will almost certainly be faster as existing works can only be looked up at the rate of 100 per sec.

Assuming the default on the second option above, the second dialog box (one per collection) will provide the analysis described.
